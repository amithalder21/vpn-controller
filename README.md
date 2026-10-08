<div align="center">

# Flotilla

**One control plane for every exit.**

Run many OpenVPN tunnels at once on a single Docker host and operate the whole
fleet from one dashboard — connect, monitor, run commands across every exit, and
stream the output live.

</div>

---

## What it does

Each `.ovpn` profile becomes an isolated **exit** — its own tunnel with its own
egress IP. From one control panel you can:

- **Manage the fleet** — upload profiles, connect/disconnect, reconnect, tag,
  rename, and delete connections. New profiles get memorable auto-generated
  names (e.g. `scarlet-beacon`); the real country/IP is shown separately.
- **See every exit at a glance** — live exit IP, country, ISP/ASN, uptime, data
  used, and health, refreshed automatically.
- **Run scripts across the fleet** — type a command or upload a `.sh`, target
  all or selected exits, and watch per-exit output stream live. Cancel a running
  job and the processes are killed inside the containers.
- **Trust the exit** — a leak test confirms traffic really leaves through the
  tunnel (exit IP ≠ host IP), and gluetun's kill-switch firewall blocks any
  un-tunnelled traffic even if a VPN drops.
- **Stay up unattended** — an auto-heal watchdog reconnects dropped/unhealthy
  tunnels, with activity logging and optional webhook alerts.
- **See the fleet geographically** — an Overview world map plots every exit at
  its egress country, colored by health, so you know where your traffic leaves
  from at a glance.
- **Watch trends** — an Overview dashboard with KPI cards (with trend arrows), a
  fleet-status donut, per-exit data bars, and time-series charts (connections
  online, healthy, data transferred) backed by a metrics history.

Everything in the UI is also a token-authenticated JSON API, so it scripts cleanly.

## Architecture

For every profile the controller runs a **worker** = two containers:

| Container        | Role                                                                |
|------------------|---------------------------------------------------------------------|
| `mvpn-<name>-vpn`| [gluetun](https://github.com/qdm12/gluetun) holding that one tunnel  |
| `mvpn-<name>-app`| shares the vpn container's netns; your commands/scripts run here     |

```
            ┌──────────────── controller (web UI + JSON API) ───────────────┐
            │  mounts /var/run/docker.sock · creates workers on demand       │
            │  auto-heal · 10s exit-IP poll · metrics · SSE streaming        │
            └──────┬────────────────────┬────────────────────┬──────────────┘
          exit A   │          exit B     │          exit C     │   ┌──────────────┐
      ┌────────────┴───┐  ┌──────────────┴─┐  ┌────────────────┴┐ │  DragonflyDB │
      │ vpn (gluetun)  │  │ vpn (gluetun)  │  │ vpn (gluetun)   │ │  (Redis API) │
      │ app  ◄shares   │  │ app  ◄shares   │  │ app  ◄shares    │ │  streams/db  │
      └──────┬─────────┘  └──────┬─────────┘  └──────┬──────────┘ └──────────────┘
          egress A            egress B            egress C
```

Because each app container shares its vpn container's network stack
(`network_mode: container:<vpn>`), **all** of its traffic exits through that
tunnel, and tunnels stay independent even with overlapping subnets.

**DragonflyDB** is the streaming bus and durable store. Script output is fanned
into a per-job Redis **stream**; the browser tails it over **SSE**, so output is
live and replays after a reload. Fleet state (desired status, tags, settings,
activity, metrics) is persisted there too.

## Quick start

```bash
cd c2
cp .env.example .env
# set a strong token (macOS shown; on Linux drop the '')
sed -i '' "s/change-me/$(openssl rand -hex 24)/" .env
docker compose -p mvpn up -d --build
```

Open **http://127.0.0.1:8088**, open **Settings**, paste the token from `.env`,
then:

1. **Connections → drop your `.ovpn` files** (one exit per file).
2. **Connect all** — a worker per profile comes up; exit IPs auto-populate.
3. **Run script** — type a command (or upload a `.sh`), **Run on all connected**,
   and watch each exit's output stream live.

## UI tour

- **Overview** — KPI cards (connections, online, healthy, data transferred) with
  trend arrows and sparklines; a world map of exit locations colored by health; a
  fleet-status donut (connected / connecting / needs attention / offline); a
  "data by exit" bar chart; plus throughput and online-over-time charts.
- **Connections** — the fleet table: name, exit location (country code + IP),
  status, and per-row quick actions (power, logs, reconnect, details). Click a
  row for a detail drawer with every fact and action. Search, filter by status,
  filter by tag, and bulk-act on a selection.
- **Run script** — script editor + library, target selection, live per-exit job
  output, cancel/stop.
- **Schedules** — run a script (saved or inline) across the fleet on a cron
  (presets or a custom 5-field expression), targeting all exits or one. See the
  next run, last run + status, enable/pause per schedule, or run one on demand.
- **Activity** — a log of connects, auto-heals, give-ups, renames, leak tests,
  and scheduled runs.
- **Settings** — control token, auto-heal toggle, webhook status, about.

## API

All `/api/*` calls require `X-Token: <CONTROL_TOKEN>` (SSE endpoints take it as
`?token=…` since EventSource can't set headers).

| Method & path                           | Does                                                            |
|-----------------------------------------|-----------------------------------------------------------------|
| `GET  /api/profiles`                    | list profiles (name, remote, proto)                             |
| `POST /api/profiles` (multipart)        | upload `.ovpn` file(s); each gets a funky name                  |
| `POST /api/profiles/<name>/tags`        | set tags `{"tags":[…]}`                                         |
| `POST /api/profiles/<name>/rename`      | rename `{"to":"…"}`                                             |
| `DELETE /api/profiles/<name>`           | delete the connection (profile + containers)                    |
| `GET  /api/workers`                     | full status of every exit (ip, country, health, stats, tags…)   |
| `POST /api/workers/<name>/<action>`     | `start` / `stop` / `restart` / `ip` / `leaktest`                |
| `GET  /api/workers/<name>/logs/stream`  | **SSE** live gluetun logs                                       |
| `POST /api/bulk/<action>`               | action across many; body `{"targets":[…]}` or omit for all      |
| `POST /api/exec`                        | one-shot command, returns output                                |
| `GET/POST/DELETE /api/scripts[/<name>]` | list / upload / read / delete `.sh` scripts                     |
| `POST /api/run`                         | stream a job: `{"script":"x.sh"\|"body":"…", "targets", "timeout"}` → job id |
| `GET  /api/jobs/<id>/stream`            | **SSE** live job output (replays + follows)                     |
| `POST /api/jobs/<id>/cancel`            | kill the job's processes (TERM, then KILL)                      |
| `GET  /api/metrics`                     | recent fleet metric points (for the charts)                     |
| `GET  /api/events`                      | recent activity                                                 |
| `GET/POST /api/settings`                | read / toggle auto-heal                                         |
| `GET/POST /api/schedules`               | list / create cron schedules `{"name","cron","script"\|"body","targets","timeout"}` |
| `POST/DELETE /api/schedules/<id>`       | update (enable, cron, target, source…) / delete a schedule      |
| `POST /api/schedules/<id>/run`          | run a schedule now → job id (tail via `/api/jobs/<id>/stream`)   |

```bash
TOK=$(grep -o '[0-9a-f]\{48\}' c2/.env)

# run a command on every connected exit and see which country each is in
curl -s -X POST -H "X-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"command":"curl -s https://ifconfig.co/country-iso","targets":"all"}' \
  http://127.0.0.1:8088/api/exec | jq
```

## Auto-heal

A watchdog reconnects exits that are meant to be up but dropped or went
unhealthy. Each connection has a **desired state** (set by Connect/Disconnect),
so a manual Disconnect is never overridden. Restarts are capped
(`HEAL_MAX_RESTARTS` within `HEAL_WINDOW`); past that the connection is flagged
**needs attention** until you reconnect it. Set `WEBHOOK_URL` for a JSON POST on
auto-heal / give-up.

**Controller env tunables:** `HEAL_INTERVAL` (20s) · `HEAL_GRACE` (120s) ·
`HEAL_MAX_RESTARTS` (3) · `HEAL_WINDOW` (900s) · `WEBHOOK_URL` (unset).

## Security

The controller **mounts the Docker socket** (root-equivalent) and runs the
scripts you submit, so treat it as privileged:

- It binds to `127.0.0.1` only and every API call requires `CONTROL_TOKEN`.
- **Never** expose port 8088 to the internet directly. For remote access use an
  SSH tunnel (`ssh -L 8088:127.0.0.1:8088 user@host`) or an authenticating proxy
  (e.g. Cloudflare Access).
- Profiles contain private keys and live only in the `mvpn-profiles` volume —
  never in git (`.gitignore` enforces this).

## Deploying on a server (Dokploy)

Use a **Docker Compose** service (not a Swarm "Application" — Swarm blocks the
`NET_ADMIN` / `/dev/net/tun` the tunnels need). Paste `c2/compose.yaml`, set
`CONTROL_TOKEN` in the Environment tab, deploy, and reach the panel over SSH.
Do not attach a public domain to it.

## `test-lab/` — self-contained demo

`test-lab/` spins up throwaway OpenVPN servers so you can see the isolation
without a real provider. `gen-pki.sh` mints a separate CA per tunnel; generated
keys are git-ignored. Not needed to use Flotilla.

## Roadmap

- **Rotating proxy pool** — expose each exit as an HTTP/SOCKS proxy plus one
  round-robin endpoint, for real per-request IP rotation across the fleet.
- WireGuard support · bulk `.zip` import (auto-named by country) · job history
  (past runs + output) · RBAC + audit · Prometheus metrics.

## Stack

Flask · docker-py · DragonflyDB (Redis-compatible) · gluetun · Debian worker
image · a dependency-free vanilla-JS single-page UI.
