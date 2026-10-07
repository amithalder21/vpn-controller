"""VPN fleet controller.

Manages N workers, one per OpenVPN profile. A worker is two containers:
  <prefix>-<profile>-vpn  gluetun holding the tunnel
  <prefix>-<profile>-app  shares the vpn container's network, so all its
                          traffic leaves through that tunnel; commands run here
Talks to the Docker engine through the mounted socket.
"""
import base64
import hmac
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import docker
import redis
from docker.errors import APIError, ImageNotFound, NotFound
from flask import Flask, Response, abort, jsonify, request, send_from_directory

PREFIX = os.environ.get("WORKER_PREFIX", "mvpn")
PROFILES_DIR = "/profiles"
SCRIPTS_DIR = "/scripts"
PROFILES_VOLUME = os.environ.get("PROFILES_VOLUME", "mvpn-profiles")
NETWORK = os.environ.get("WORKER_NETWORK", "mvpn-net")
VPN_IMAGE = os.environ.get("VPN_IMAGE", "qmcgaw/gluetun:latest")
APP_IMAGE = os.environ.get("APP_IMAGE", "curlimages/curl:latest")
TOKEN = os.environ.get("CONTROL_TOKEN", "")
TZ = os.environ.get("TZ", "UTC")
REDIS_URL = os.environ.get("REDIS_URL", "redis://dragonfly:6379/0")
JOB_TTL = 6 * 3600  # keep a job's streamed output in Dragonfly this long
MAX_OUTPUT = 64 * 1024
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

client = docker.from_env()
pool = ThreadPoolExecutor(max_workers=32)
rdb = redis.Redis.from_url(REDIS_URL, decode_responses=True)
ip_cache = {}        # profile -> {"ip":..., "country":..., "checked": epoch}
leak_cache = {}      # profile -> {"pass": bool, "exit_ip":..., "checked": epoch}
stats_cache = {}     # profile -> {"cpu": %, "mem_mb": float, "rx_mb":..., "tx_mb":...}
_stat_prev = {}      # profile -> (total_cpu, system_cpu)  for delta cpu%
heal_state = {}      # profile -> {"restarts": int, "last": epoch, "gaveup": bool}
unhealthy_since = {} # profile -> epoch when it first went unhealthy
rotate_last = {}     # profile -> epoch of last auto-rotate

# Auto-heal tuning (env-overridable)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
HEAL_INTERVAL = int(os.environ.get("HEAL_INTERVAL", "20"))     # watchdog tick
HEAL_GRACE = int(os.environ.get("HEAL_GRACE", "120"))         # unhealthy tolerance
HEAL_MAX = int(os.environ.get("HEAL_MAX_RESTARTS", "3"))      # before giving up
HEAL_WINDOW = int(os.environ.get("HEAL_WINDOW", "900"))       # restart-count window

app = Flask(__name__, static_folder="static")


# ---------- persistent fleet state (DragonflyDB) ----------

def _rtry(fn, default=None):
    try:
        return fn()
    except redis.RedisError:
        return default

def desired_get(name):
    return _rtry(lambda: rdb.hget("mvpn:desired", name))

def desired_set(name, val):
    _rtry(lambda: rdb.hset("mvpn:desired", name, val))

def desired_del(name):
    _rtry(lambda: rdb.hdel("mvpn:desired", name))

def tags_get(name):
    raw = _rtry(lambda: rdb.hget("mvpn:tags", name))
    try:
        return json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []

def tags_set(name, tags):
    _rtry(lambda: rdb.hset("mvpn:tags", name, json.dumps(tags)))

def tags_del(name):
    _rtry(lambda: rdb.hdel("mvpn:tags", name))

def rotate_get(name):
    return _rtry(lambda: rdb.hget("mvpn:rotate", name)) or 0

def rotate_set(name, minutes):
    if minutes and int(minutes) > 0:
        _rtry(lambda: rdb.hset("mvpn:rotate", name, int(minutes)))
    else:
        _rtry(lambda: rdb.hdel("mvpn:rotate", name))

def setting_get(key, default):
    v = _rtry(lambda: rdb.hget("mvpn:settings", key))
    return default if v is None else v

def setting_set(key, val):
    _rtry(lambda: rdb.hset("mvpn:settings", key, val))

def record_event(name, kind, detail=""):
    _rtry(lambda: rdb.xadd("mvpn:events",
          {"ts": str(int(time.time())), "name": name, "kind": kind, "detail": detail},
          maxlen=1000, approximate=True))

def heal_reset(name):
    heal_state.pop(name, None)
    unhealthy_since.pop(name, None)

def alert(name, kind, detail=""):
    if not WEBHOOK_URL:
        return
    import urllib.request
    body = json.dumps({"name": name, "event": kind, "detail": detail,
                       "ts": int(time.time())}).encode()
    req = urllib.request.Request(WEBHOOK_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8).close()
    except Exception:
        pass


# ---------- helpers ----------

def clean_name(raw):
    """Profile name from a filename: lowercase, dashes, no extension."""
    base = re.sub(r"\.(ovpn|conf)$", "", raw.strip(), flags=re.I).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40]
    if not NAME_RE.match(base):
        abort(400, f"invalid profile name: {raw!r}")
    return base


def profile_path(name):
    return os.path.join(PROFILES_DIR, f"{name}.ovpn")


def profile_summary(name):
    remote, proto = None, None
    try:
        with open(profile_path(name), encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if not parts or parts[0].startswith(("#", ";")):
                    continue
                if parts[0] == "remote" and remote is None and len(parts) > 1:
                    remote = " ".join(parts[1:3])
                elif parts[0] == "proto" and proto is None and len(parts) > 1:
                    proto = parts[1]
    except FileNotFoundError:
        pass
    return {"name": name, "remote": remote, "proto": proto}


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith(".ovpn"))


def cname(name, role):
    return f"{PREFIX}-{name}-{role}"


def get(name, role):
    try:
        return client.containers.get(cname(name, role))
    except NotFound:
        return None


def ensure_image(image):
    try:
        client.images.get(image)
    except ImageNotFound:
        # locally-built images (no registry) can't be pulled
        if "/" not in image or image.startswith("mvpn-"):
            abort(500, f"image {image} is missing; run: docker compose build")
        client.images.pull(image)


def worker_status(name):
    vpn, wapp = get(name, "vpn"), get(name, "app")
    out = {"name": name, "exists": bool(vpn or wapp)}
    if vpn:
        state = vpn.attrs["State"]
        out["vpn"] = state["Status"]
        out["health"] = (state.get("Health") or {}).get("Status")
        out["started_at"] = state.get("StartedAt")
    if wapp:
        out["app"] = wapp.attrs["State"]["Status"]
    out["ipinfo"] = ip_cache.get(name)
    out["stats"] = stats_cache.get(name)
    out["leak"] = leak_cache.get(name)
    out["rotate_min"] = int(rotate_get(name) or 0)
    out["desired"] = desired_get(name) or "down"
    out["tags"] = tags_get(name)
    hs = heal_state.get(name)
    out["restarts"] = hs["restarts"] if hs else 0
    out["gaveup"] = bool(hs and hs["gaveup"])
    return out


def create_worker(name):
    ensure_image(VPN_IMAGE)
    ensure_image(APP_IMAGE)
    labels = {"mvpn.profile": name}
    vpn = client.containers.run(
        VPN_IMAGE,
        name=cname(name, "vpn"),
        detach=True,
        cap_add=["NET_ADMIN"],
        devices=["/dev/net/tun:/dev/net/tun"],
        environment={
            "VPN_SERVICE_PROVIDER": "custom",
            "VPN_TYPE": "openvpn",
            "OPENVPN_CUSTOM_CONFIG": profile_path(name),
            "TZ": TZ,
        },
        volumes={PROFILES_VOLUME: {"bind": PROFILES_DIR, "mode": "ro"}},
        network=NETWORK,
        restart_policy={"Name": "unless-stopped"},
        labels={**labels, "mvpn.role": "vpn"},
    )
    client.containers.run(
        APP_IMAGE,
        command=["sleep", "infinity"],
        name=cname(name, "app"),
        detach=True,
        network_mode=f"container:{vpn.id}",
        restart_policy={"Name": "unless-stopped"},
        labels={**labels, "mvpn.role": "app"},
    )


def _bounce(name):
    """Low-level restart used by the watchdog (no desired/heal bookkeeping)."""
    vpn, wapp = get(name, "vpn"), get(name, "app")
    if vpn is None:
        if wapp:
            wapp.remove(force=True)
        create_worker(name)
        return
    vpn.restart(timeout=5)
    if wapp:
        wapp.restart(timeout=2)  # rebind to the vpn's fresh netns
    ip_cache.pop(name, None)


def start_worker(name):
    if not os.path.exists(profile_path(name)):
        abort(404, f"no profile {name}")
    desired_set(name, "up"); heal_reset(name); record_event(name, "connect")
    vpn, wapp = get(name, "vpn"), get(name, "app")
    if not vpn:
        if wapp:  # orphaned app container without its network owner
            wapp.remove(force=True)
        create_worker(name)
        return
    vpn.start()
    if wapp:
        wapp.restart(timeout=2)


def stop_worker(name):
    desired_set(name, "down"); heal_reset(name); record_event(name, "disconnect")
    for role in ("app", "vpn"):
        c = get(name, role)
        if c:
            c.stop(timeout=5)


def restart_worker(name):
    desired_set(name, "up"); heal_reset(name); record_event(name, "reconnect")
    _bounce(name)


def remove_worker(name):
    for role in ("app", "vpn"):
        c = get(name, role)
        if c:
            c.remove(force=True)
    desired_del(name); heal_reset(name)
    ip_cache.pop(name, None); stats_cache.pop(name, None); _stat_prev.pop(name, None)
    record_event(name, "removed")


def exec_in(name, command, timeout=60):
    wapp = get(name, "app")
    if not wapp or wapp.status != "running":
        return {"exit": None, "output": "worker app container is not running", "ms": 0}
    t0 = time.time()
    res = wapp.exec_run(["timeout", str(int(timeout)), "sh", "-c", command])
    out = (res.output or b"").decode("utf-8", errors="replace")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n…[truncated]"
    return {"exit": res.exit_code, "output": out, "ms": int((time.time() - t0) * 1000)}


def check_ip(name):
    # ifconfig.co is used over ipinfo.io because the latter rate-limits (429)
    # shared NAT exits quickly, blanking the IP for all but the first worker.
    r = exec_in(name, "curl -s -m 15 https://ifconfig.co/json", timeout=20)
    info = {"checked": int(time.time())}
    try:
        data = json.loads(r["output"])
        info.update({
            "ip": data.get("ip"),
            "city": data.get("city"),
            "region": data.get("region_name"),
            "country": data.get("country"),
            "country_iso": data.get("country_iso"),
            "org": (f'{data["asn"]} {data.get("asn_org", "")}'.strip()
                    if data.get("asn") else data.get("asn_org")),
        })
    except (ValueError, TypeError):
        info["error"] = (r["output"] or "no response").strip()[:200]
    ip_cache[name] = info
    return info


_host_ip = {"ip": None, "at": 0}

def host_public_ip():
    """The controller host's own public IP (NOT via any tunnel), cached 1h."""
    if _host_ip["ip"] and time.time() - _host_ip["at"] < 3600:
        return _host_ip["ip"]
    try:
        import urllib.request
        ip = urllib.request.urlopen("https://ifconfig.co/ip", timeout=8).read().decode().strip()
        _host_ip.update(ip=ip, at=time.time())
    except Exception:
        pass
    return _host_ip["ip"]


def leak_test(name):
    """Confirm traffic actually exits through the tunnel, not the host."""
    info = check_ip(name)  # refresh exit IP
    host = host_public_ip()
    exit_ip = info.get("ip")
    if info.get("error") or not exit_ip:
        res = {"pass": False, "reason": info.get("error") or "no exit IP", "exit_ip": None}
    elif host and exit_ip == host:
        res = {"pass": False, "reason": "exit IP equals host IP — traffic is NOT tunnelled",
               "exit_ip": exit_ip}
    else:
        res = {"pass": True, "exit_ip": exit_ip, "host_ip": host,
               "country": info.get("country"), "country_iso": info.get("country_iso")}
    res["checked"] = int(time.time())
    leak_cache[name] = res
    record_event(name, "leaktest", "pass" if res["pass"] else "fail: " + res.get("reason", ""))
    return res


def rotate_ip(name):
    """Reconnect to pull a fresh session/exit, then re-check the IP shortly after."""
    old = (ip_cache.get(name) or {}).get("ip")
    restart_worker(name)
    record_event(name, "rotate", f"from {old}" if old else "")

    def _recheck():
        time.sleep(18)
        info = check_ip(name)
        if info.get("ip") and info["ip"] != old:
            record_event(name, "rotated", f"{old} → {info['ip']}")
    threading.Thread(target=_recheck, daemon=True).start()
    return {"rotating": True, "old_ip": old}


def fan_out(names, fn):
    futures = {n: pool.submit(fn, n) for n in names}
    results = {}
    for n, fut in futures.items():
        try:
            results[n] = fut.result()
        except Exception as e:  # report per-worker failures instead of failing the batch
            results[n] = {"error": str(e)}
    return results


def resolve_targets(targets):
    if targets in (None, "all", ["all"]):
        return [n for n in list_profiles() if get(n, "app")]
    return [clean_name(t) for t in targets]


# ---------- scripts & streaming jobs (via DragonflyDB) ----------

def list_scripts():
    if not os.path.isdir(SCRIPTS_DIR):
        return []
    return sorted(f for f in os.listdir(SCRIPTS_DIR) if f.endswith(".sh"))


def script_path(name):
    name = clean_name(re.sub(r"\.sh$", "", name)) + ".sh"
    return os.path.join(SCRIPTS_DIR, name), name


def job_key(job_id):
    return f"job:{job_id}"


def publish(job_id, **fields):
    """Append one event to the job's Dragonfly stream."""
    rdb.xadd(job_key(job_id), {k: str(v) for k, v in fields.items()},
             maxlen=10000, approximate=True)
    rdb.expire(job_key(job_id), JOB_TTL)


def stream_exec(name, script_b64, timeout, job_id):
    """Run the decoded script in one worker, streaming its output live."""
    wapp = get(name, "app")
    if not wapp or wapp.status != "running":
        publish(job_id, worker=name, event="exit", code="-1",
                line="worker not running\n")
        return
    # Decode to a temp file and execute it so the script's own shebang decides
    # the interpreter (bash is available in the worker image); files with no
    # shebang fall back to sh. tr strips CR so CRLF uploads don't break. The
    # outer `timeout` sets rc=124 on overrun, which we surface below.
    # Scripts with their own shebang run as-is (bash/sh as they ask); scripts
    # with no shebang — e.g. an inline command — run under bash, because
    # `timeout <file>` cannot exec a shebang-less file (it would exit 126).
    runner = (
        'd=$(mktemp); echo "$MVPN_B64" | base64 -d | tr -d "\\r" > "$d"; '
        'chmod +x "$d"; '
        f'if head -c2 "$d" | grep -q "^#!"; then timeout {int(timeout)} "$d"; '
        f'else timeout {int(timeout)} bash "$d"; fi; '
        'rc=$?; rm -f "$d"; exit $rc'
    )
    cmd = ["sh", "-c", runner]
    try:
        # MVPN_JOB is inherited by every process the script spawns, so cancel
        # can find and kill the whole tree (see cancel_in).
        ex = client.api.exec_create(
            wapp.id, cmd, tty=False,
            environment={"MVPN_B64": script_b64, "MVPN_JOB": job_id})
        buf = ""
        for chunk in client.api.exec_start(ex["Id"], stream=True):
            buf += chunk.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                publish(job_id, worker=name, line=line + "\n")
        if buf:
            publish(job_id, worker=name, line=buf + "\n")
        code = client.api.exec_inspect(ex["Id"]).get("ExitCode")
        publish(job_id, worker=name, event="exit",
                code=("124" if code == 124 else str(code)))
    except APIError as e:
        publish(job_id, worker=name, event="exit", code="-1",
                line=f"error: {e.explanation or e}\n")


# Kills every process in a worker tagged with the given job id (parent sh,
# timeout, the script and anything it spawned), TERM then KILL.
KILL_SH = r'''
jid="$1"
match() { tr '\0' '\n' < "$1/environ" 2>/dev/null | grep -Fxq "MVPN_JOB=$jid"; }
n=0
for p in /proc/[0-9]*; do match "$p" && { kill -TERM "${p#/proc/}" 2>/dev/null && n=$((n+1)); }; done
sleep 1
for p in /proc/[0-9]*; do match "$p" && kill -KILL "${p#/proc/}" 2>/dev/null; done
echo "$n"
'''


def cancel_in(name, job_id):
    wapp = get(name, "app")
    if not wapp or wapp.status != "running":
        return {"killed": 0, "skipped": "not running"}
    res = wapp.exec_run(["sh", "-c", KILL_SH, "_", job_id])
    out = (res.output or b"").decode(errors="replace").strip()
    return {"killed": int(out) if out.isdigit() else 0}


def cancel_job(job_id, names):
    result = fan_out(names, lambda n: cancel_in(n, job_id))
    publish(job_id, event="cancel",
            total=sum(v.get("killed", 0) for v in result.values()))
    return result


def run_job(script_b64, names, timeout):
    """Start one streaming exec per target, then mark the job done."""
    job_id = uuid.uuid4().hex[:12]
    publish(job_id, event="start", workers=json.dumps(names),
            count=len(names))

    def coordinator():
        futures = [pool.submit(stream_exec, n, script_b64, timeout, job_id)
                   for n in names]
        for f in futures:
            f.result()
        publish(job_id, event="done")

    threading.Thread(target=coordinator, daemon=True).start()
    return job_id


def sse(generator):
    return Response(generator, mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


def job_events(job_id):
    """SSE: replay then follow a job's Dragonfly stream to the browser."""
    last = "0"
    while True:
        resp = rdb.xread({job_key(job_id): last}, block=15000, count=200)
        if not resp:
            yield ": ping\n\n"
            continue
        for _, entries in resp:
            for eid, fields in entries:
                last = eid
                yield f"data: {json.dumps(fields)}\n\n"
                if fields.get("event") == "done":
                    return


def container_log_events(name, tail):
    """SSE: follow a worker's gluetun logs live."""
    vpn = get(name, "vpn")
    if not vpn:
        yield f"data: {json.dumps({'line': 'worker not found'})}\n\n"
        return
    for raw in vpn.logs(stream=True, follow=True, tail=tail):
        yield f"data: {json.dumps({'line': raw.decode('utf-8', errors='replace')})}\n\n"


# ---------- auth ----------

@app.before_request
def require_token():
    if not request.path.startswith("/api/") or not TOKEN:
        return
    given = request.headers.get("X-Token") or ""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        given = auth[7:]
    # SSE (EventSource) cannot set headers, so stream routes accept ?token=
    if not given:
        given = request.args.get("token", "")
    if not hmac.compare_digest(given.encode(), TOKEN.encode()):
        abort(401, "missing or wrong token")


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
def http_error(e):
    return jsonify(error=e.description), e.code


@app.errorhandler(APIError)
def docker_error(e):
    return jsonify(error=str(e.explanation or e)), 502


# ---------- routes ----------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/profiles")
def api_profiles():
    return jsonify([profile_summary(n) for n in list_profiles()])


@app.post("/api/profiles")
def api_upload_profiles():
    files = request.files.getlist("files")
    if not files:
        abort(400, "send one or more files in the 'files' field")
    saved = []
    for f in files:
        name = clean_name(f.filename or "")
        data = f.read()
        if b"remote " not in data:
            abort(400, f"{f.filename}: does not look like an OpenVPN profile (no 'remote' line)")
        with open(profile_path(name), "wb") as out:
            out.write(data)
        os.chmod(profile_path(name), 0o644)  # gluetun reads it as a non-root user
        saved.append(name)
    return jsonify(saved=saved)


@app.delete("/api/profiles/<name>")
def api_delete_profile(name):
    name = clean_name(name)
    remove_worker(name)
    try:
        os.remove(profile_path(name))
    except FileNotFoundError:
        abort(404, f"no profile {name}")
    return jsonify(deleted=name)


@app.get("/api/workers")
def api_workers():
    return jsonify([worker_status(n) for n in list_profiles()])


@app.post("/api/workers/<name>/<action>")
def api_worker_action(name, action):
    name = clean_name(name)
    actions = {"start": start_worker, "stop": stop_worker, "restart": restart_worker}
    if action == "ip":
        return jsonify(check_ip(name))
    if action == "leaktest":
        return jsonify(leak_test(name))
    if action == "rotate":
        return jsonify(rotate_ip(name))
    if action not in actions:
        abort(404, f"unknown action {action}")
    actions[action](name)
    return jsonify(worker_status(name))


@app.post("/api/workers/<name>/rotate-schedule")
def api_rotate_schedule(name):
    name = clean_name(name)
    body = request.get_json(silent=True) or {}
    rotate_set(name, body.get("minutes", 0))
    record_event(name, "rotate-schedule", f"{rotate_get(name)}m" if rotate_get(name) else "off")
    return jsonify(name=name, rotate_min=int(rotate_get(name) or 0))


@app.delete("/api/workers/<name>")
def api_worker_remove(name):
    name = clean_name(name)
    remove_worker(name)
    return jsonify(removed=name)


@app.get("/api/workers/<name>/logs")
def api_worker_logs(name):
    vpn = get(clean_name(name), "vpn")
    if not vpn:
        abort(404, "worker not found")
    tail = min(int(request.args.get("tail", 100)), 2000)
    return jsonify(logs=vpn.logs(tail=tail).decode("utf-8", errors="replace"))


@app.post("/api/bulk/<action>")
def api_bulk(action):
    body = request.get_json(silent=True) or {}
    if action == "start":
        names = [clean_name(t) for t in body["targets"]] if body.get("targets") else list_profiles()
        return jsonify(fan_out(names, lambda n: (start_worker(n), worker_status(n))[1]))
    names = resolve_targets(body.get("targets"))
    fns = {"stop": stop_worker, "restart": restart_worker, "remove": remove_worker, "ip": check_ip}
    if action not in fns:
        abort(404, f"unknown bulk action {action}")
    return jsonify(fan_out(names, lambda n: fns[action](n) or {"ok": True}))


@app.post("/api/exec")
def api_exec():
    body = request.get_json(silent=True) or {}
    command = (body.get("command") or "").strip()
    if not command:
        abort(400, "command is required")
    timeout = max(1, min(int(body.get("timeout", 60)), 600))
    names = resolve_targets(body.get("targets"))
    return jsonify(fan_out(names, lambda n: exec_in(n, command, timeout)))


# ---- scripts ----

@app.get("/api/scripts")
def api_scripts():
    return jsonify(list_scripts())


@app.post("/api/scripts")
def api_upload_script():
    files = request.files.getlist("files")
    if not files:
        abort(400, "send one or more .sh files in the 'files' field")
    saved = []
    for f in files:
        if not (f.filename or "").endswith(".sh"):
            abort(400, f"{f.filename}: not a .sh file")
        path, name = script_path(f.filename)
        f.save(path)
        saved.append(name)
    return jsonify(saved=saved)


@app.get("/api/scripts/<name>")
def api_get_script(name):
    path, _ = script_path(name)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return jsonify(name=os.path.basename(path), body=fh.read())
    except FileNotFoundError:
        abort(404, "no such script")


@app.delete("/api/scripts/<name>")
def api_delete_script(name):
    path, _ = script_path(name)
    try:
        os.remove(path)
    except FileNotFoundError:
        abort(404, "no such script")
    return jsonify(deleted=os.path.basename(path))


# ---- streaming jobs ----

@app.post("/api/run")
def api_run():
    """Run an uploaded script OR an inline body across workers, streaming output.

    Body: {"script": "<name.sh>"} or {"body": "<shell>"}, plus
    "targets" ("all" or [names]) and optional "timeout".
    Returns a job id; tail it at GET /api/jobs/<id>/stream.
    """
    body = request.get_json(silent=True) or {}
    if body.get("script"):
        path, _ = script_path(body["script"])
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except FileNotFoundError:
            abort(404, "no such script")
    elif body.get("body"):
        raw = body["body"].encode()
    else:
        abort(400, "provide 'script' (a saved name) or 'body' (inline shell)")
    names = resolve_targets(body.get("targets"))
    if not names:
        abort(400, "no running workers to target")
    timeout = max(1, min(int(body.get("timeout", 300)), 3600))
    script_b64 = base64.b64encode(raw).decode()
    job_id = run_job(script_b64, names, timeout)
    return jsonify(job=job_id, targets=names)


@app.get("/api/jobs/<job_id>/stream")
def api_job_stream(job_id):
    if not re.fullmatch(r"[0-9a-f]{6,32}", job_id):
        abort(400, "bad job id")
    return sse(job_events(job_id))


def job_targets(job_id):
    """Recover a job's target workers from its recorded start event."""
    try:
        for _eid, fields in rdb.xrange(job_key(job_id), count=1):
            if fields.get("workers"):
                return json.loads(fields["workers"])
    except (redis.RedisError, ValueError):
        pass
    return []


@app.post("/api/jobs/<job_id>/cancel")
def api_job_cancel(job_id):
    if not re.fullmatch(r"[0-9a-f]{6,32}", job_id):
        abort(400, "bad job id")
    body = request.get_json(silent=True) or {}
    if body.get("targets"):
        names = [clean_name(t) for t in body["targets"]]
    else:
        names = job_targets(job_id) or resolve_targets(None)
    return jsonify(cancel_job(job_id, names))


@app.get("/api/workers/<name>/logs/stream")
def api_logs_stream(name):
    name = clean_name(name)
    tail = min(int(request.args.get("tail", 100)), 2000)
    return sse(container_log_events(name, tail))


# ---- settings (auto-heal) & activity ----

@app.get("/api/settings")
def api_get_settings():
    return jsonify(autoheal=setting_get("autoheal", "1") == "1",
                   webhook=bool(WEBHOOK_URL))


@app.post("/api/settings")
def api_set_settings():
    body = request.get_json(silent=True) or {}
    if "autoheal" in body:
        setting_set("autoheal", "1" if body["autoheal"] else "0")
        record_event("-", "autoheal-" + ("on" if body["autoheal"] else "off"))
    return api_get_settings()


@app.get("/api/events")
def api_events():
    limit = min(int(request.args.get("limit", 60)), 500)
    try:
        rows = rdb.xrevrange("mvpn:events", count=limit)
    except redis.RedisError:
        rows = []
    return jsonify([{**f, "id": i} for i, f in rows])


# ---- tags & rename ----

@app.post("/api/profiles/<name>/tags")
def api_set_tags(name):
    name = clean_name(name)
    body = request.get_json(silent=True) or {}
    tags = [str(t).strip()[:24] for t in (body.get("tags") or []) if str(t).strip()]
    tags_set(name, sorted(set(tags)))
    return jsonify(name=name, tags=tags_get(name))


@app.post("/api/profiles/<name>/rename")
def api_rename(name):
    name = clean_name(name)
    body = request.get_json(silent=True) or {}
    new = clean_name(body.get("to") or "")
    if not os.path.exists(profile_path(name)):
        abort(404, f"no profile {name}")
    if os.path.exists(profile_path(new)):
        abort(400, f"name {new} already exists")
    remove_worker(name)                       # containers recreated under new name
    os.rename(profile_path(name), profile_path(new))
    if tags_get(name):
        tags_set(new, tags_get(name)); tags_del(name)
    record_event(new, "renamed", f"from {name}")
    return jsonify(renamed={"from": name, "to": new})


# ---------- background workers ----------

def _heal(name, reason):
    hs = heal_state.setdefault(name, {"restarts": 0, "last": 0, "gaveup": False})
    now = time.time()
    if now - hs["last"] > HEAL_WINDOW:
        hs["restarts"] = 0
    if hs["restarts"] >= HEAL_MAX:
        if not hs["gaveup"]:
            hs["gaveup"] = True
            record_event(name, "gaveup", reason)
            alert(name, "gaveup", reason)
        return
    hs["restarts"] += 1
    hs["last"] = now
    unhealthy_since.pop(name, None)
    try:
        _bounce(name)
        record_event(name, "autoheal", f"{reason} (#{hs['restarts']})")
        alert(name, "autoheal", reason)
    except Exception as e:
        record_event(name, "heal-error", str(e)[:120])


def _heal_once():
    if setting_get("autoheal", "1") != "1":
        return
    for name in list_profiles():
        if desired_get(name) != "up":
            continue
        hs = heal_state.get(name)
        if hs and hs["gaveup"]:
            continue
        vpn = get(name, "vpn")
        try:
            if vpn is None:
                _heal(name, "missing")
                continue
            vpn.reload()
            state = vpn.attrs["State"]
            status = state["Status"]
            health = (state.get("Health") or {}).get("Status")
            if status != "running":
                _heal(name, "stopped")
            elif health == "unhealthy":
                since = unhealthy_since.setdefault(name, time.time())
                if time.time() - since >= HEAL_GRACE:
                    _heal(name, "unhealthy")
            else:
                unhealthy_since.pop(name, None)
        except Exception:
            continue


def _cpu_pct(name, s):
    cs = s.get("cpu_stats", {})
    tot = cs.get("cpu_usage", {}).get("total_usage", 0)
    sysu = cs.get("system_cpu_usage", 0)
    ncpu = cs.get("online_cpus") or len(cs.get("cpu_usage", {}).get("percpu_usage") or [1]) or 1
    prev = _stat_prev.get(name)
    _stat_prev[name] = (tot, sysu)
    if not prev:
        return 0.0
    cd, sd = tot - prev[0], sysu - prev[1]
    return round((cd / sd) * ncpu * 100, 1) if sd > 0 and cd > 0 else 0.0


def _stats_once():
    for name in list_profiles():
        wapp = get(name, "app")
        if not wapp or wapp.status != "running":
            stats_cache.pop(name, None)
            _stat_prev.pop(name, None)
            continue
        try:
            s = wapp.stats(stream=False)
            mem = s.get("memory_stats", {}).get("usage", 0)
            # data usage: encrypted tunnel traffic on the vpn container's uplink
            rx = tx = 0
            vpn = get(name, "vpn")
            if vpn:
                for net in (vpn.stats(stream=False).get("networks") or {}).values():
                    rx += net.get("rx_bytes", 0); tx += net.get("tx_bytes", 0)
            stats_cache[name] = {"cpu": _cpu_pct(name, s), "mem_mb": round(mem / 1048576, 1),
                                 "rx_mb": round(rx / 1048576, 1), "tx_mb": round(tx / 1048576, 1)}
        except Exception:
            continue


def _rotate_once():
    """Auto-rotate exit IP for connections with a rotation interval set."""
    now = time.time()
    for name in list_profiles():
        mins = int(rotate_get(name) or 0)
        if not mins or desired_get(name) != "up":
            continue
        last = rotate_last.get(name, 0)
        if now - last >= mins * 60:
            rotate_last[name] = now
            try:
                rotate_ip(name)
            except Exception:
                pass


def _loop(fn, interval):
    while True:
        try:
            fn()
        except Exception:
            pass
        time.sleep(interval)


if __name__ == "__main__":
    os.makedirs(PROFILES_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    threading.Thread(target=_loop, args=(_heal_once, HEAL_INTERVAL), daemon=True).start()
    threading.Thread(target=_loop, args=(_stats_once, 8), daemon=True).start()
    threading.Thread(target=_loop, args=(_rotate_once, 30), daemon=True).start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
