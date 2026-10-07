# VPN Controller

Run **N OpenVPN connections at once** on one Docker host and drive them from a
single control panel. Each VPN profile gets its own isolated worker; a command
you issue from the controller runs inside whichever worker(s) you pick, so each
one leaves through its own tunnel.

## How it works

For every `.ovpn` profile the controller manages a **worker** = two containers:

| Container        | Role                                                                    |
|------------------|-------------------------------------------------------------------------|
| `mvpn-<p>-vpn`   | [gluetun](https://github.com/qdm12/gluetun) holding that one tunnel      |
| `mvpn-<p>-app`   | shares the vpn container's network; your commands/scripts run here      |

```
          ┌──────────────── controller (web UI + API) ───────────────┐
          │  mounts /var/run/docker.sock, creates workers on demand   │
          │  streams script output + logs through DragonflyDB (SSE)   │
          └──────┬───────────────────┬───────────────────┬───────────┘
        worker A │           worker B │          worker C │     ┌────────────┐
      ┌──────────┴─────┐   ┌──────────┴─────┐   ┌─────────┴──┐  │ DragonflyDB │
      │ vpn (gluetun)  │   │ vpn (gluetun)  │   │ vpn        │  │ (Redis API) │
      │ app  ◄shares   │   │ app  ◄shares   │   │ app ◄shares│  │  streams    │
      └──────┬─────────┘   └──────┬─────────┘   └──────┬─────┘  └────────────┘
          tunnel A             tunnel B             tunnel C
```

Because each app container shares its vpn container's network stack
(`network_mode: container:<vpn>`), **all** of its traffic exits through that VPN,
and the tunnels stay independent even if they use overlapping subnets.

**DragonflyDB sidecar** is the streaming bus. When you run a script, the
controller fans it out to every target worker and writes each line of output
into a per-job Redis **stream** in Dragonfly. The browser tails that stream over
**SSE**, so output appears live and survives a page reload (replayed from the
stream, which is kept for 6 h). Live gluetun logs stream the same way.

## Quick start

```bash
cd c2
cp .env.example .env
sed -i '' "s/change-me/$(openssl rand -hex 24)/" .env   # Linux: drop the ''
docker compose -p mvpn up -d --build
```

Open http://127.0.0.1:8088, paste the token from `.env`, then:

1. **Upload** your `.ovpn` files (or drop them in the `mvpn-profiles` volume).
2. **Start all** — one worker per profile comes up.
3. **Check all IPs** — confirms each worker's exit location.
4. Type a command, **Run on all / selected** — it executes in every chosen worker.

Everything the UI does is also available on the JSON API (see below), so you can
script it.

## API

All `/api/*` calls need `X-Token: <CONTROL_TOKEN>`.

| Method & path                       | Does                                        |
|-------------------------------------|---------------------------------------------|
| `GET  /api/profiles`                | list uploaded profiles                      |
| `POST /api/profiles` (multipart)    | upload one or more `.ovpn` files            |
| `DELETE /api/profiles/<name>`       | remove worker + delete the profile          |
| `GET  /api/workers`                 | status + cached exit IP of every worker     |
| `POST /api/workers/<name>/<action>` | `start` / `stop` / `restart` / `ip`         |
| `DELETE /api/workers/<name>`        | remove the worker (keep the profile)        |
| `GET  /api/workers/<name>/logs`     | gluetun logs (`?tail=200`)                  |
| `POST /api/bulk/<action>`           | same actions across many; body `{"targets":[...]}` or omit for all |
| `POST /api/exec`                    | `{"command":"...","targets":"all","timeout":60}` one-shot, returns output |
| `GET  /api/scripts`                 | list uploaded `.sh` scripts                 |
| `POST /api/scripts` (multipart)     | upload one or more `.sh` scripts            |
| `GET/DELETE /api/scripts/<name>`    | read / delete a script                      |
| `POST /api/run`                     | stream a job: `{"script":"x.sh"}` or `{"body":"<shell>"}` + `targets`, `timeout`; returns a job id |
| `GET  /api/jobs/<id>/stream`        | **SSE** live output of a job (replays + follows) |
| `POST /api/jobs/<id>/cancel`        | kill that job's processes in the workers (TERM, then KILL) |
| `GET/POST /api/settings`            | read / toggle auto-heal (`{"autoheal":true}`) |
| `GET  /api/events`                  | recent activity (connects, auto-heals, renames…) |
| `POST /api/profiles/<name>/tags`    | set tags (`{"tags":["eu","scraping"]}`) |
| `POST /api/profiles/<name>/rename`  | rename a connection (`{"to":"new-name"}`) |
| `GET  /api/workers/<name>/logs/stream` | **SSE** live gluetun logs                 |

SSE endpoints can't send headers, so they take the token as `?token=<CONTROL_TOKEN>`.

```bash
# upload a script, run it on every worker, and watch output live
curl -s -H "X-Token: $TOK" -F files=@probe.sh http://127.0.0.1:8088/api/scripts
ID=$(curl -s -X POST -H "X-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"script":"probe.sh","targets":"all"}' http://127.0.0.1:8088/api/run | jq -r .job)
curl -N "http://127.0.0.1:8088/api/jobs/$ID/stream?token=$TOK"
```

```bash
TOK=$(grep -o '[0-9a-f]\{48\}' c2/.env)
curl -s -X POST -H "X-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"command":"curl -s https://ifconfig.co/json","targets":"all"}' \
  http://127.0.0.1:8088/api/exec | jq
```

## Auto-heal

A background watchdog reconnects connections that are meant to be up but have
dropped or gone unhealthy. Each connection tracks a desired state (set when you
Connect/Disconnect), so a manual Disconnect is never fought by the watchdog.
Restarts are capped (`HEAL_MAX_RESTARTS` within `HEAL_WINDOW`); after that a
connection is marked **needs attention** until you reconnect it. Toggle it from
the header; set `WEBHOOK_URL` to receive a JSON POST on auto-heal / give-up.

Tunables (env on the controller): `HEAL_INTERVAL` (20s), `HEAL_GRACE` (120s
unhealthy tolerance), `HEAL_MAX_RESTARTS` (3), `HEAL_WINDOW` (900s).

## Security

The controller **mounts the Docker socket**, which is equivalent to root on the
host. Therefore:

- It binds to `127.0.0.1` only, and every API call requires `CONTROL_TOKEN`.
- **Do not** expose port 8088 to the internet or through a tunnel. For remote
  access use an SSH tunnel (`ssh -L 8088:127.0.0.1:8088 user@host`) or put it
  behind an authenticating proxy / Cloudflare Access.
- Profiles hold private keys and are kept in the `mvpn-profiles` Docker volume,
  never in git.

## `test-lab/` — optional self-contained demo

`test-lab/` runs its own throwaway OpenVPN servers so you can see the isolation
without any real provider. `gen-pki.sh` mints a separate CA per tunnel; the
generated keys are git-ignored. Not needed to use the controller.

## Deploying on Dokploy

Create a **Docker Compose** service (not an Application — Swarm blocks the
`NET_ADMIN`/`/dev/net/tun` the tunnels need), paste `c2/compose.yaml`, set
`CONTROL_TOKEN` in the Environment tab, and deploy. Reach the panel over SSH;
don't attach a public domain to it.
