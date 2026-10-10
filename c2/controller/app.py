"""VPN fleet controller.

Manages N workers, one per OpenVPN profile. A worker is two containers:
  <prefix>-<profile>-vpn  gluetun holding the tunnel
  <prefix>-<profile>-app  shares the vpn container's network, so all its
                          traffic leaves through that tunnel; commands run here
Talks to the Docker engine through the mounted socket.
"""
import base64
import hmac
import io
import json
import os
import re
import shutil
import socket
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

import docker
import redis
from docker.errors import APIError, ImageNotFound, NotFound
from flask import Flask, Response, abort, jsonify, request, send_from_directory

PREFIX = os.environ.get("WORKER_PREFIX", "mvpn")
PROFILES_DIR = "/profiles"
SCRIPTS_DIR = "/scripts"
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")
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

# ---- proxy pool: expose each exit as an HTTP proxy (gluetun's built-in :8888),
#      published to 127.0.0.1 per exit, plus one round-robin front on the controller.
PROXY_POOL = os.environ.get("PROXY_POOL", "on").lower() not in ("0", "off", "false", "no")
PROXY_PORT_BASE = int(os.environ.get("PROXY_PORT_BASE", "12000"))  # per-exit host ports from here up
PROXY_RR_PORT = int(os.environ.get("PROXY_RR_PORT", "18080"))      # round-robin listener (in-container)
GLUETUN_PROXY_PORT = 8888  # gluetun HTTPPROXY listen port inside each exit's netns

client = docker.from_env()
pool = ThreadPoolExecutor(max_workers=32)
rdb = redis.Redis.from_url(REDIS_URL, decode_responses=True)
ip_cache = {}        # profile -> {"ip":..., "country":..., "checked": epoch}
leak_cache = {}      # profile -> {"pass": bool, "exit_ip":..., "checked": epoch}
stats_cache = {}     # profile -> {"cpu": %, "mem_mb": float, "rx_mb":..., "tx_mb":...}
_stat_prev = {}      # profile -> (total_cpu, system_cpu)  for delta cpu%
heal_state = {}      # profile -> {"restarts": int, "last": epoch, "gaveup": bool}
unhealthy_since = {} # profile -> epoch when it first went unhealthy

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


def setting_get(key, default):
    v = _rtry(lambda: rdb.hget("mvpn:settings", key))
    return default if v is None else v

def setting_set(key, val):
    _rtry(lambda: rdb.hset("mvpn:settings", key, val))


def proxy_port(name):
    """Stable host port for this exit's HTTP proxy (persisted, allocated lazily)."""
    cur = _rtry(lambda: rdb.hget("mvpn:proxyports", name))
    if cur:
        try:
            return int(cur)
        except ValueError:
            pass
    allp = _rtry(lambda: rdb.hgetall("mvpn:proxyports")) or {}
    used = set()
    for v in allp.values():
        try:
            used.add(int(v))
        except ValueError:
            pass
    port = PROXY_PORT_BASE
    while port in used:
        port += 1
    _rtry(lambda: rdb.hset("mvpn:proxyports", name, str(port)))
    return port


def proxy_port_del(name):
    _rtry(lambda: rdb.hdel("mvpn:proxyports", name))


def proxy_pool_enabled(name):
    """Whether this exit participates in the round-robin pool (default yes)."""
    return _rtry(lambda: rdb.hget("mvpn:proxyoff", name)) != "1"


def proxy_pool_set(name, enabled):
    if enabled:
        _rtry(lambda: rdb.hdel("mvpn:proxyoff", name))
    else:
        _rtry(lambda: rdb.hset("mvpn:proxyoff", name, "1"))

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


# ---------- scheduled jobs (cron) ----------

def _parse_cron_field(expr, lo, hi, dow=False):
    """Parse one cron field into a set of ints, or None for '*' (any)."""
    expr = expr.strip()
    if expr == "*":
        return None
    vals = set()
    for part in expr.split(","):
        rng, step = (part.split("/", 1) + ["1"])[:2] if "/" in part else (part, "1")
        step = int(step)
        if step < 1:
            raise ValueError("step must be >= 1")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = (int(x) for x in rng.split("-", 1))
        else:
            a = b = int(rng)
        if a > b or a < lo or b > hi:
            raise ValueError(f"value out of range {lo}-{hi}")
        for v in range(a, b + 1, step):
            vals.add(0 if (dow and v == 7) else v)
    return vals


def parse_cron(expr):
    """Parse a 5-field cron expression (min hour dom mon dow) -> field sets."""
    parts = (expr or "").split()
    if len(parts) != 5:
        raise ValueError("cron needs 5 fields: min hour dom mon dow")
    return [
        _parse_cron_field(parts[0], 0, 59),
        _parse_cron_field(parts[1], 0, 23),
        _parse_cron_field(parts[2], 1, 31),
        _parse_cron_field(parts[3], 1, 12),
        _parse_cron_field(parts[4], 0, 7, dow=True),
    ]


def cron_match(fields, tm):
    """True if local-time struct tm satisfies the parsed cron fields."""
    f_min, f_hour, f_dom, f_mon, f_dow = fields
    ok = lambda s, v: s is None or v in s
    cron_dow = (tm.tm_wday + 1) % 7  # py Mon=0..Sun=6  ->  cron Sun=0..Sat=6
    if f_dom is None and f_dow is None:
        day = True
    elif f_dom is not None and f_dow is not None:   # cron: either matches
        day = tm.tm_mday in f_dom or cron_dow in f_dow
    elif f_dom is not None:
        day = tm.tm_mday in f_dom
    else:
        day = cron_dow in f_dow
    return (ok(f_min, tm.tm_min) and ok(f_hour, tm.tm_hour)
            and ok(f_mon, tm.tm_mon) and day)


def cron_next(expr, after_epoch):
    """Next epoch (whole minute) strictly after after_epoch that matches, or None."""
    try:
        fields = parse_cron(expr)
    except ValueError:
        return None
    t = (int(after_epoch) // 60 + 1) * 60
    for _ in range(366 * 24 * 60):          # search up to ~1 year
        if cron_match(fields, time.localtime(t)):
            return t
        t += 60
    return None


def schedules_all():
    raw = _rtry(lambda: rdb.hgetall("mvpn:schedules")) or {}
    out = []
    for js in raw.values():
        try:
            out.append(json.loads(js))
        except ValueError:
            pass
    out.sort(key=lambda s: s.get("created_at", 0))
    return out


def schedule_get(sid):
    js = _rtry(lambda: rdb.hget("mvpn:schedules", sid))
    try:
        return json.loads(js) if js else None
    except ValueError:
        return None


def schedule_put(s):
    _rtry(lambda: rdb.hset("mvpn:schedules", s["id"], json.dumps(s)))


def schedule_del(sid):
    _rtry(lambda: rdb.hdel("mvpn:schedules", sid))


def schedule_payload(s):
    """Script bytes for a schedule: its saved script, or its inline body."""
    if s.get("script"):
        path, _ = script_path(s["script"])
        with open(path, "rb") as fh:
            return fh.read()
    if s.get("body"):
        return s["body"].encode()
    return None


def _fire_schedule(s, manual=False):
    """Run a schedule now. Returns (job_id, names) or raises ValueError."""
    raw = schedule_payload(s)
    if raw is None:
        raise ValueError("source missing (script deleted?)")
    names = resolve_targets(s.get("targets"))
    if not names:
        raise ValueError("no running workers to target")
    label = s.get("name") or s.get("script") or "schedule"
    job_id = run_job(base64.b64encode(raw).decode(), names, int(s.get("timeout", 300)), label=label)
    s["last_run"] = int(time.time())
    s["last_job"] = job_id
    s["last_status"] = f"ran on {len(names)}"
    schedule_put(s)
    tag = " (manual)" if manual else ""
    record_event("-", "schedule", f'{s.get("name", "")}{tag} -> {len(names)} exit(s)')
    return job_id, names


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
    out["desired"] = desired_get(name) or "down"
    out["tags"] = tags_get(name)
    hs = heal_state.get(name)
    out["restarts"] = hs["restarts"] if hs else 0
    out["gaveup"] = bool(hs and hs["gaveup"])
    if PROXY_POOL:
        published = None
        if vpn:
            pm = (vpn.attrs.get("NetworkSettings") or {}).get("Ports") or {}
            b = pm.get(f"{GLUETUN_PROXY_PORT}/tcp")
            if b:
                try:
                    published = int(b[0]["HostPort"])
                except (KeyError, ValueError, IndexError, TypeError):
                    published = None
        # "active" = the container actually publishes the proxy port (recreated
        # since the feature was enabled); "online" = reachable & healthy now.
        out["proxy"] = {
            "port": published if published else proxy_port(name),
            "active": bool(published),
            "online": bool(published and out.get("vpn") == "running" and out.get("health") == "healthy"),
            "pool": proxy_pool_enabled(name),
        }
    return out


def create_worker(name):
    ensure_image(VPN_IMAGE)
    ensure_image(APP_IMAGE)
    labels = {"mvpn.profile": name}
    env = {
        "VPN_SERVICE_PROVIDER": "custom",
        "VPN_TYPE": "openvpn",
        "OPENVPN_CUSTOM_CONFIG": profile_path(name),
        "TZ": TZ,
    }
    ports = None
    if PROXY_POOL:
        # gluetun's own HTTP proxy, egressing through this exit's tunnel,
        # published only on the host loopback at a stable per-exit port.
        env["HTTPPROXY"] = "on"
        env["HTTPPROXY_LOG"] = "off"
        # gluetun drops inbound by default; open the proxy port so it's
        # reachable from the Docker network (round-robin front) and from the
        # published host port (docker-proxy DNAT lands in this netns too).
        env["FIREWALL_INPUT_PORTS"] = str(GLUETUN_PROXY_PORT)
        ports = {f"{GLUETUN_PROXY_PORT}/tcp": ("127.0.0.1", proxy_port(name))}
    vpn = client.containers.run(
        VPN_IMAGE,
        name=cname(name, "vpn"),
        detach=True,
        cap_add=["NET_ADMIN"],
        devices=["/dev/net/tun:/dev/net/tun"],
        environment=env,
        ports=ports,
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


def _proxy_configured(vpn):
    """True if this vpn container was created with the proxy port published."""
    pb = (vpn.attrs.get("HostConfig") or {}).get("PortBindings") or {}
    return f"{GLUETUN_PROXY_PORT}/tcp" in pb


def _needs_recreate(vpn):
    """Config drift: proxy pool on but this exit predates it (no proxy port)."""
    return PROXY_POOL and vpn is not None and not _proxy_configured(vpn)


def _recreate(name):
    for role in ("app", "vpn"):
        c = get(name, role)
        if c:
            c.remove(force=True)
    create_worker(name)
    ip_cache.pop(name, None)


def _bounce(name):
    """Low-level restart used by the watchdog (no desired/heal bookkeeping)."""
    vpn, wapp = get(name, "vpn"), get(name, "app")
    if vpn is None:
        if wapp:
            wapp.remove(force=True)
        create_worker(name)
        return
    if _needs_recreate(vpn):     # migrate drifted exits to the current config
        _recreate(name)
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
    if _needs_recreate(vpn):     # pick up proxy settings on connect
        _recreate(name)
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
    desired_del(name); heal_reset(name); proxy_port_del(name)
    _rtry(lambda: rdb.hdel("mvpn:proxyoff", name))


# ---------- proxy pool: round-robin front ----------
# Each exit's gluetun exposes an HTTP proxy on :8888 inside its netns, reachable
# from the controller over the Docker network at <vpn-container-ip>:8888. The
# round-robin front accepts a client on PROXY_RR_PORT and transparently relays
# the whole connection to the next healthy exit's proxy (one exit per connection).

def _exit_proxy_target(name):
    """(_ip_, 8888) for a running exit on the Docker network, or None."""
    vpn = get(name, "vpn")
    if not vpn or (vpn.attrs.get("State") or {}).get("Status") != "running":
        return None
    nets = (vpn.attrs.get("NetworkSettings") or {}).get("Networks") or {}
    net = nets.get(NETWORK) or next(iter(nets.values()), None)
    ip = net.get("IPAddress") if net else None
    return (ip, GLUETUN_PROXY_PORT) if ip else None


_rr_lock = threading.Lock()
_rr_i = 0

def _rr_order():
    """Healthy exits as (name, (ip, port)), rotated so each call starts at the
    next one (round-robin), with the rest as failover candidates."""
    cand = []
    for n in list_profiles():
        s = worker_status(n)
        if s.get("vpn") == "running" and s.get("health") == "healthy" and proxy_pool_enabled(n):
            t = _exit_proxy_target(n)
            if t:
                cand.append((n, t))
    if not cand:
        return []
    global _rr_i
    with _rr_lock:
        start = _rr_i % len(cand)
        _rr_i += 1
    return cand[start:] + cand[:start]

def _rr_pick():
    """Next healthy exit in round-robin order, or None."""
    order = _rr_order()
    return order[0] if order else None


def _pump(src, dst):
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _handle_rr(cli):
    try:
        order = _rr_order()
        if not order:
            cli.sendall(b"HTTP/1.1 503 Service Unavailable\r\n\r\nno healthy exit\n")
            return
        up = None
        for _name, target in order:               # try each healthy exit in turn
            try:
                up = socket.create_connection(target, timeout=8)
                break
            except OSError:
                up = None
        if up is None:
            cli.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n"
                        b"exit proxy unreachable (is the exit reconnected so "
                        b"gluetun's HTTP proxy is enabled?)\n")
            return
        t = threading.Thread(target=_pump, args=(cli, up), daemon=True)
        t.start()
        _pump(up, cli)
    except OSError:
        pass
    finally:
        try:
            cli.close()
        except OSError:
            pass


def _rr_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PROXY_RR_PORT))
    srv.listen(128)
    while True:
        try:
            cli, _ = srv.accept()
        except OSError:
            continue
        threading.Thread(target=_handle_rr, args=(cli,), daemon=True).start()
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


def seed_example_scripts():
    """Copy bundled example scripts into SCRIPTS_DIR when missing.

    Non-destructive: a script of the same name (e.g. one the user edited) is
    never overwritten; a deleted default simply reappears on next start.
    """
    if not os.path.isdir(EXAMPLES_DIR):
        return
    for fn in sorted(os.listdir(EXAMPLES_DIR)):
        if not fn.endswith(".sh"):
            continue
        dst = os.path.join(SCRIPTS_DIR, fn)
        if os.path.exists(dst):
            continue
        try:
            shutil.copyfile(os.path.join(EXAMPLES_DIR, fn), dst)
        except OSError:
            pass


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


def _job_meta_set(meta):
    _rtry(lambda: rdb.hset("mvpn:jobs", meta["id"], json.dumps(meta)))

def _job_meta_update(job_id, **fields):
    raw = _rtry(lambda: rdb.hget("mvpn:jobs", job_id))
    if not raw:
        return
    try:
        d = json.loads(raw)
    except ValueError:
        return
    d.update(fields)
    _rtry(lambda: rdb.hset("mvpn:jobs", job_id, json.dumps(d)))

def _job_meta_trim(keep=150):
    raw = _rtry(lambda: rdb.hgetall("mvpn:jobs")) or {}
    if len(raw) <= keep:
        return
    rows = []
    for jid, js in raw.items():
        try:
            rows.append((json.loads(js).get("ts", 0), jid))
        except ValueError:
            rows.append((0, jid))
    rows.sort()
    for _ts, jid in rows[:len(rows) - keep]:
        _rtry(lambda j=jid: rdb.hdel("mvpn:jobs", j))


def run_job(script_b64, names, timeout, label=None):
    """Start one streaming exec per target, then mark the job done."""
    job_id = uuid.uuid4().hex[:12]
    publish(job_id, event="start", workers=json.dumps(names),
            count=len(names))
    _job_meta_set({"id": job_id, "ts": int(time.time()), "label": label or "command",
                   "count": len(names), "targets": names,
                   "status": "running", "finished_at": None})
    _job_meta_trim()

    def coordinator():
        futures = [pool.submit(stream_exec, n, script_b64, timeout, job_id)
                   for n in names]
        for f in futures:
            f.result()
        publish(job_id, event="done")
        _job_meta_update(job_id, status="done", finished_at=int(time.time()))

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
@app.errorhandler(502)
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


FUNKY_ADJ = ["swift", "crimson", "azure", "silent", "rogue", "tidal", "coral", "misty",
             "salty", "amber", "shadow", "golden", "drifting", "restless", "iron", "velvet",
             "storm", "frost", "ember", "dusky", "cobalt", "jade", "scarlet", "midnight"]
FUNKY_NOUN = ["marlin", "otter", "kraken", "nomad", "corsair", "mariner", "petrel", "narwhal",
              "orca", "gull", "barracuda", "tern", "albatross", "dolphin", "seahorse", "manta",
              "urchin", "compass", "anchor", "harbor", "beacon", "reef", "current", "voyager"]

def funky_name():
    import random
    for _ in range(80):
        n = f"{random.choice(FUNKY_ADJ)}-{random.choice(FUNKY_NOUN)}"
        if not os.path.exists(profile_path(n)):
            return n
    return "exit-" + uuid.uuid4().hex[:6]


def _looks_like_ovpn(data: bytes) -> bool:
    return b"remote " in data


def _save_ovpn(data: bytes, label: str = "profile") -> str:
    """Validate bytes as an OpenVPN profile and store it under a funky name."""
    if not _looks_like_ovpn(data):
        abort(400, f"{label}: does not look like an OpenVPN profile (no 'remote' line)")
    name = funky_name()  # memorable name; country/IP are shown separately
    with open(profile_path(name), "wb") as out:
        out.write(data)
    os.chmod(profile_path(name), 0o644)  # gluetun reads it as a non-root user
    return name


# Browser-ish UA; some free-config hosts 403 the default urllib agent.
_FETCH_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_FETCH_MAX = 8 * 1024 * 1024  # 8 MiB cap per download


def _http_get(url: str, timeout: int = 20) -> tuple[bytes, str]:
    """Fetch a URL server-side. Returns (body, content_type). Raises ValueError on failure."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("URL must be http(s) and absolute")
    req = urllib.request.Request(url, headers={"User-Agent": _FETCH_UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            return resp.read(_FETCH_MAX + 1)[:_FETCH_MAX], ctype
    except urllib.error.HTTPError as e:
        raise ValueError(f"{url}: HTTP {e.code} {e.reason}")
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise ValueError(f"{url}: {getattr(e, 'reason', e)}")


def _extract_ovpns(data: bytes) -> list[bytes]:
    """Pull every .ovpn out of a zip/tar archive; [] if it isn't an archive."""
    out = []
    try:
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".ovpn"):
                        out.append(z.read(n))
            return out
    except zipfile.BadZipFile:
        pass
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            for m in t.getmembers():
                if m.isfile() and m.name.lower().endswith(".ovpn"):
                    f = t.extractfile(m)
                    if f:
                        out.append(f.read())
    except (tarfile.TarError, OSError):
        pass
    return out


@app.post("/api/profiles")
def api_upload_profiles():
    files = request.files.getlist("files")
    if not files:
        abort(400, "send one or more files in the 'files' field")
    saved = [_save_ovpn(f.read(), f.filename or "profile") for f in files]
    return jsonify(saved=saved)


@app.post("/api/profiles/fetch")
def api_fetch_profile():
    """Import profiles from a URL (.ovpn or .zip/.tar archive) or pasted raw config."""
    body = request.get_json(silent=True) or {}
    raw = (body.get("raw") or "").strip()
    url = (body.get("url") or "").strip()
    if raw:
        return jsonify(saved=[_save_ovpn(raw.encode("utf-8"), "pasted config")])
    if not url:
        abort(400, "provide 'url' or 'raw'")
    try:
        data, _ = _http_get(url)
    except ValueError as e:
        abort(502, str(e))
    archived = _extract_ovpns(data)
    if archived:
        saved = [_save_ovpn(d, f"{url} entry") for d in archived if _looks_like_ovpn(d)]
        if not saved:
            abort(400, "archive contained no usable .ovpn profiles")
        return jsonify(saved=saved)
    return jsonify(saved=[_save_ovpn(data, url)])


# ipspeed.info free-OpenVPN listing. Best-effort: the page is often behind a
# Cloudflare human-check that will 403 this server-side fetch, in which case we
# say so and the user falls back to the URL/paste import above.
IPSPEED_URL = "https://ipspeed.info/free-openvpn.php"


@app.post("/api/profiles/ipspeed")
def api_fetch_ipspeed():
    try:
        page, _ = _http_get(IPSPEED_URL)
    except ValueError as e:
        abort(502, f"could not reach ipspeed.info ({e}). Grab the .ovpn link in your "
                   f"browser and use Import from URL / paste instead.")
    text = page.decode("utf-8", "replace")
    blocked = ("Just a moment" in text or "security verification" in text
               or "cf-challenge" in text or "challenge-platform" in text)
    if blocked:
        abort(502, "ipspeed.info is behind a Cloudflare human-check right now. Open it in "
                   "your browser, copy a server's .ovpn link, and use Import from URL / paste.")
    # Collect candidate config links: anchors ending in .ovpn or hitting a
    # download endpoint. Resolve relative hrefs against the page URL.
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', text, flags=re.I)
    cands, seen = [], set()
    for h in hrefs:
        low = h.lower()
        if low.endswith(".ovpn") or "ovpn" in low and ("download" in low or "data" in low or "config" in low):
            full = urllib.parse.urljoin(IPSPEED_URL, h)
            if full not in seen:
                seen.add(full)
                cands.append(full)
    if not cands:
        abort(502, "no .ovpn links found on the page (its layout may have changed). Use "
                   "Import from URL / paste with a direct link from your browser.")
    saved, errors = [], []
    for c in cands[:40]:
        try:
            data, _ = _http_get(c)
            for d in (_extract_ovpns(data) or [data]):
                if _looks_like_ovpn(d):
                    saved.append(_save_ovpn(d, c))
        except ValueError as e:
            errors.append(str(e))
    if not saved:
        abort(502, "found links but none yielded a usable profile. " + ("; ".join(errors[:3])))
    return jsonify(saved=saved, found=len(cands), errors=errors[:5])


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
    if body.get("script"):
        label = body["script"]
    else:
        first = (body.get("body", "").strip().splitlines() or [""])[0]
        label = first[:60] or "command"
    script_b64 = base64.b64encode(raw).decode()
    job_id = run_job(script_b64, names, timeout, label=label)
    return jsonify(job=job_id, targets=names)


@app.get("/api/jobs")
def api_jobs_list():
    limit = min(int(request.args.get("limit", 50)), 200)
    raw = _rtry(lambda: rdb.hgetall("mvpn:jobs")) or {}
    out = []
    for js in raw.values():
        try:
            out.append(json.loads(js))
        except ValueError:
            pass
    out.sort(key=lambda m: m.get("ts", 0), reverse=True)
    return jsonify(out[:limit])


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


@app.get("/api/proxy")
def api_proxy():
    """Proxy-pool summary: whether it's on, the round-robin port, and per-exit ports."""
    exits = []
    if PROXY_POOL:
        for n in list_profiles():
            s = worker_status(n)
            p = s.get("proxy") or {}
            exits.append({"name": n, "port": p.get("port"),
                          "active": p.get("active", False), "online": p.get("online", False),
                          "pool": p.get("pool", True)})
    return jsonify(enabled=PROXY_POOL, rr_port=PROXY_RR_PORT,
                   port_base=PROXY_PORT_BASE, scheme="http", host="127.0.0.1",
                   exits=exits)


@app.post("/api/proxy/<name>")
def api_proxy_toggle(name):
    """Include/exclude an exit from the round-robin pool. Body: {"pool": bool}."""
    name = clean_name(name)
    body = request.get_json(silent=True) or {}
    proxy_pool_set(name, bool(body.get("pool", True)))
    return jsonify(name=name, pool=proxy_pool_enabled(name))


# ---- scheduled jobs ----

def _validate_source(body, cur=None):
    """Resolve script/body from a request into (script, body); raise 400s."""
    script = (body.get("script") or "").strip()
    text = body.get("body") or ""
    if script:
        path, _ = script_path(script)
        if not os.path.isfile(path):
            abort(400, "no such script")
        return script, ""
    if text.strip():
        if len(text) > 100000:
            abort(400, "script too long")
        return "", text
    if cur and (cur.get("script") or cur.get("body")):
        return cur.get("script", ""), cur.get("body", "")
    abort(400, "provide 'script' (a saved name) or 'body' (inline shell)")


def _validate_targets(t):
    if t in (None, "all"):
        return "all"
    if isinstance(t, list):
        return [clean_name(x) for x in t if str(x).strip()]
    abort(400, "targets must be 'all' or a list of names")


def _schedule_public(s, now):
    d = {k: v for k, v in s.items() if k != "last_bucket"}
    d["next_run"] = cron_next(s.get("cron", ""), now) if s.get("enabled", True) else None
    return d


@app.get("/api/schedules")
def api_schedules():
    now = int(time.time())
    return jsonify([_schedule_public(s, now) for s in schedules_all()])


@app.post("/api/schedules")
def api_schedule_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()[:60]
    if not name:
        abort(400, "name required")
    cron = (body.get("cron") or "").strip()
    try:
        parse_cron(cron)
    except ValueError as e:
        abort(400, f"bad cron: {e}")
    script, text = _validate_source(body)
    s = {
        "id": uuid.uuid4().hex[:8], "name": name, "cron": cron,
        "targets": _validate_targets(body.get("targets", "all")),
        "script": script, "body": text,
        "timeout": max(1, min(int(body.get("timeout", 300)), 3600)),
        "enabled": bool(body.get("enabled", True)),
        "created_at": int(time.time()),
        "last_run": None, "last_job": None, "last_status": None, "last_bucket": None,
    }
    schedule_put(s)
    record_event("-", "schedule-add", name)
    return jsonify(_schedule_public(s, int(time.time())))


@app.post("/api/schedules/<sid>")
def api_schedule_update(sid):
    s = schedule_get(sid)
    if not s:
        abort(404, "no such schedule")
    body = request.get_json(silent=True) or {}
    if "name" in body and (body["name"] or "").strip():
        s["name"] = body["name"].strip()[:60]
    if "cron" in body:
        try:
            parse_cron(body["cron"])
        except ValueError as e:
            abort(400, f"bad cron: {e}")
        s["cron"] = body["cron"].strip()
    if "enabled" in body:
        s["enabled"] = bool(body["enabled"])
    if "timeout" in body:
        s["timeout"] = max(1, min(int(body["timeout"]), 3600))
    if "targets" in body:
        s["targets"] = _validate_targets(body["targets"])
    if "script" in body or "body" in body:
        s["script"], s["body"] = _validate_source(body, s)
    schedule_put(s)
    return jsonify(_schedule_public(s, int(time.time())))


@app.delete("/api/schedules/<sid>")
def api_schedule_delete(sid):
    s = schedule_get(sid)
    if not s:
        abort(404, "no such schedule")
    schedule_del(sid)
    record_event("-", "schedule-del", s.get("name", sid))
    return jsonify(deleted=sid)


@app.post("/api/schedules/<sid>/run")
def api_schedule_run_now(sid):
    s = schedule_get(sid)
    if not s:
        abort(404, "no such schedule")
    try:
        job_id, names = _fire_schedule(s, manual=True)
    except ValueError as e:
        abort(400, str(e))
    return jsonify(job=job_id, targets=names)


@app.get("/api/metrics")
def api_metrics():
    limit = min(int(request.args.get("limit", 120)), 2880)
    try:
        rows = list(reversed(rdb.xrevrange("mvpn:metrics", count=limit)))
    except redis.RedisError:
        rows = []
    out = []
    for _id, f in rows:
        pt = {}
        for k, v in f.items():
            try:
                pt[k] = int(v) if k in ("ts", "conns", "online", "healthy", "countries") else float(v)
            except (ValueError, TypeError):
                pt[k] = v
        out.append(pt)
    return jsonify(out)


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


def _ipcheck_once():
    """Keep each healthy tunnel's exit IP fresh (~every 10s) so the UI always
    reflects the real egress — never a stale IP while sending traffic."""
    now = time.time()
    for name in list_profiles():
        vpn = get(name, "vpn")
        if not vpn:
            continue
        try:
            vpn.reload()
            state = vpn.attrs["State"]
            if state["Status"] != "running" or (state.get("Health") or {}).get("Status") != "healthy":
                continue
        except Exception:
            continue
        info = ip_cache.get(name)
        if info and not info.get("error") and now - info.get("checked", 0) < 10:
            continue
        try:
            check_ip(name)
        except Exception:
            pass


def _metrics_once():
    """Snapshot fleet-wide metrics for the Overview sparklines (~48h at 60s)."""
    names = list_profiles()
    online = healthy = 0
    countries = set()
    rx = tx = 0.0
    for name in names:
        st = stats_cache.get(name)
        if st:
            rx += st.get("rx_mb", 0) or 0
            tx += st.get("tx_mb", 0) or 0
        info = ip_cache.get(name)
        if info and info.get("country_iso"):
            countries.add(info["country_iso"])
        vpn = get(name, "vpn")
        if vpn:
            try:
                vpn.reload()
                state = vpn.attrs["State"]
                if state["Status"] == "running":
                    online += 1
                    if (state.get("Health") or {}).get("Status") == "healthy":
                        healthy += 1
            except Exception:
                pass
    rec = {"ts": str(int(time.time())), "conns": str(len(names)), "online": str(online),
           "healthy": str(healthy), "countries": str(len(countries)),
           "rx": str(round(rx, 1)), "tx": str(round(tx, 1))}
    _rtry(lambda: rdb.xadd("mvpn:metrics", rec, maxlen=2880, approximate=True))


def _schedules_once():
    """Cron tick: fire any enabled schedule due this minute (once per minute)."""
    now = int(time.time())
    bucket = now // 60
    tm = time.localtime(now)
    for s in schedules_all():
        if not s.get("enabled", True) or s.get("last_bucket") == bucket:
            continue
        try:
            fields = parse_cron(s.get("cron", ""))
        except ValueError:
            continue
        if not cron_match(fields, tm):
            continue
        s["last_bucket"] = bucket            # claim this minute before running
        try:
            _fire_schedule(s)
        except ValueError as e:
            s["last_run"] = now
            s["last_status"] = f"skipped: {e}"
            schedule_put(s)
            record_event("-", "schedule-skip", f'{s.get("name", "")}: {e}')


def _loop(fn, interval):
    while True:
        try:
            fn()
        except Exception:
            pass
        time.sleep(interval)


if __name__ == "__main__":
    try:
        time.tzset()          # honour TZ so cron fields are local time
    except Exception:
        pass
    os.makedirs(PROFILES_DIR, exist_ok=True)
    os.makedirs(SCRIPTS_DIR, exist_ok=True)
    seed_example_scripts()
    threading.Thread(target=_loop, args=(_heal_once, HEAL_INTERVAL), daemon=True).start()
    threading.Thread(target=_loop, args=(_stats_once, 8), daemon=True).start()
    threading.Thread(target=_loop, args=(_ipcheck_once, 10), daemon=True).start()
    threading.Thread(target=_loop, args=(_metrics_once, 60), daemon=True).start()
    threading.Thread(target=_loop, args=(_schedules_once, 20), daemon=True).start()
    if PROXY_POOL:
        threading.Thread(target=_rr_server, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
