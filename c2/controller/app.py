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
ip_cache = {}  # profile -> {"ip":..., "country":..., "checked": epoch}

app = Flask(__name__, static_folder="static")


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


def start_worker(name):
    if not os.path.exists(profile_path(name)):
        abort(404, f"no profile {name}")
    vpn, wapp = get(name, "vpn"), get(name, "app")
    if not vpn:
        if wapp:  # orphaned app container without its network owner
            wapp.remove(force=True)
        create_worker(name)
        return
    vpn.start()
    if wapp:
        # app shares the vpn netns; restart it so it binds to the live one
        wapp.restart(timeout=2)


def stop_worker(name):
    for role in ("app", "vpn"):
        c = get(name, role)
        if c:
            c.stop(timeout=5)


def restart_worker(name):
    vpn, wapp = get(name, "vpn"), get(name, "app")
    if not vpn:
        return start_worker(name)
    vpn.restart(timeout=5)
    if wapp:
        wapp.restart(timeout=2)
    ip_cache.pop(name, None)


def remove_worker(name):
    for role in ("app", "vpn"):
        c = get(name, role)
        if c:
            c.remove(force=True)
    ip_cache.pop(name, None)


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
            "org": (f'{data["asn"]} {data.get("asn_org", "")}'.strip()
                    if data.get("asn") else data.get("asn_org")),
        })
    except (ValueError, TypeError):
        info["error"] = (r["output"] or "no response").strip()[:200]
    ip_cache[name] = info
    return info


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
    runner = (
        'd=$(mktemp); echo "$MVPN_B64" | base64 -d | tr -d "\\r" > "$d"; '
        f'chmod +x "$d"; timeout {int(timeout)} "$d"; rc=$?; rm -f "$d"; exit $rc'
    )
    cmd = ["sh", "-c", runner]
    try:
        ex = client.api.exec_create(
            wapp.id, cmd, tty=False, environment={"MVPN_B64": script_b64})
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
    if action not in actions:
        abort(404, f"unknown action {action}")
    actions[action](name)
    return jsonify(worker_status(name))


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


@app.get("/api/workers/<name>/logs/stream")
def api_logs_stream(name):
    name = clean_name(name)
    tail = min(int(request.args.get("tail", 100)), 2000)
    return sse(container_log_events(name, tail))


if __name__ == "__main__":
    os.makedirs(PROFILES_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=8080, threaded=True)
