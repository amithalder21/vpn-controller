<div align="center">

# 🛰️ Flotilla

### The control plane for your VPN exit fleet

Spin up dozens of VPN exits, watch them on a **live world map**, run commands
across all of them at once, and keep every tunnel healthy — from one dashboard.

![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Self-hosted](https://img.shields.io/badge/self--hosted-yes-0a7d41)
![API](https://img.shields.io/badge/API-token--auth%20JSON-5b8cff)
![Status](https://img.shields.io/badge/status-active-brightgreen)

[Features](#-features) ·
[Use cases](#-use-cases) ·
[Quickstart](#-quickstart) ·
[Architecture](#-architecture) ·
[API](#-api--integrations) ·
[Security](#-security--trust)

</div>

---

## Overview

Running one VPN is easy. Running **twenty** — each with its own exit IP, country,
and health — turns into a mess of terminals, scripts, and guesswork. Flotilla
makes a fleet of exits feel like a single system.

Each `.ovpn` profile becomes an isolated **exit**: its own tunnel, its own egress
IP. From one control plane you see every exit on a live map, act on the whole
fleet at once, run and schedule scripts, and let a watchdog keep tunnels healthy.

- **One pane of glass** — every exit's location, IP, ISP, health, uptime, data,
  and live throughput, refreshed automatically.
- **Act on the whole fleet** — connect, reconnect, tag, and run scripts across all
  exits (or a selection) with per-exit output streaming live.
- **Self-healing** — a watchdog reconnects dropped tunnels; a kill-switch firewall
  blocks any traffic that isn't tunnelled.
- **Automate it** — schedule jobs on a cron, review run history, get webhook alerts.

> Flotilla is **free, open, and self-hosted** — it runs on your own Docker host.
> Everything in the UI is also a **token-authenticated JSON API**, so your
> dashboards, CI, and scripts drive the same control plane.

---

## 🎯 Use cases

Flotilla shines whenever you need to **do the same thing from many network
vantage points at once — reliably, and from one place.**

### Testing & QA
- **Geo-testing** — verify your site/app/CDN serves the right content, prices,
  language, and consent banners from many countries at once.
- **Geo-blocking & licensing checks** — confirm region-locked content is blocked
  (or allowed) exactly where it should be.
- **CDN & DNS validation** — see which edge POP or DNS answer each region gets;
  catch misrouting before customers do.
- **Multi-region latency & uptime probes** — lightweight synthetic monitoring
  without paying per-region for a probe network.

### Ad, marketing & SEO verification
- **Ad verification** — check campaigns render correctly and to the right audience
  per country; spot cloaked or fraudulent creatives.
- **SERP & localization checks** — see how search results and localized pages look
  per region.
- **Price & availability monitoring** — track how listings vary by geography.

### Security & research
- **Malware / URL detonation** — fetch suspicious URLs from disposable exits so
  your real IP and network stay unexposed; the kill-switch fails **closed**.
- **Authorized pentesting / red-team** — exercise your own perimeter from varied
  source IPs; validate IP allow/deny lists and rate-limiting.
- **Egress & leak validation** — the built-in leak test proves traffic truly exits
  via the tunnel (exit IP ≠ host IP).

### Infrastructure & operations
- **Fleet operations** — one dashboard to connect, monitor, and heal many VPN
  provider endpoints instead of juggling separate clients.
- **Scheduled, distributed collection** — run legitimate data pulls across exits on
  a cron, with run history and alerts (always within each site's ToS and the law).
- **Resilient unattended egress** — auto-heal keeps tunnels up; webhooks ping you
  only when something needs a human.

> **Responsible use.** Flotilla is built for testing, monitoring, and research on
> systems you own or are authorized to assess. The same multi-IP capability can be
> abused (ban evasion, credential stuffing, ToS-violating scraping, fraud) — don't.
> It is single-operator and localhost-only by default, not an abuse platform.

---

## ✨ Features

### Fleet management
- Drag-and-drop `.ovpn` profiles — each becomes an isolated **exit** with its own
  tunnel and egress IP.
- Memorable auto-generated names (e.g. `scarlet-beacon`); real country/IP shown
  separately. Rename, tag, connect/disconnect/reconnect, delete — individually or
  in bulk.

### Proxy pool
- **Each exit is an HTTP proxy** on `127.0.0.1` (gluetun's built-in proxy,
  egressing through that exit's tunnel) — point any tool (browser, `curl`, Burp,
  scanners) at a specific country.
- **Round-robin endpoint** rotates across healthy exits per connection, for
  per-connection IP rotation across the fleet.
- Addresses and state are shown under **Settings → Proxy pool** (copy-ready).
  Loopback-only by design; tunnel over SSH for remote use. Toggle with `PROXY_POOL`.

### Observability
- **Live world map** of every exit, plotted by egress country and colored by health.
- **Overview dashboard** — KPI cards with trend arrows, a fleet-status donut, a
  "data by exit" bar chart, and **live throughput** (MB/s) per exit and fleet-wide.
- **Live logs & metrics** streamed over SSE; history that replays after a reload.

### Automation
- **Run scripts across the fleet** — inline command or uploaded `.sh`, targeting all
  or selected exits, per-exit output streaming live, one-click cancel.
- **Schedules (cron)** — run any script on a schedule (presets or a custom 5-field
  expression); see next/last run, enable or pause, or run on demand.
- **Job history** — browse recent runs and re-open their output.
- **Built-in QA/perf scripts** — `geo-check`, `latency`, `throughput`, and
  `uptime-probe` ship by default in the script library (edit the `TARGET` at the
  top and run on all exits). See [`c2/controller/examples/`](c2/controller/examples/).

### Trust & safety
- **Leak test** confirms traffic really leaves through the tunnel (exit IP ≠ host IP).
- **Kill-switch firewall** (via gluetun) blocks un-tunnelled traffic even if a VPN drops.
- **Auto-heal** reconnects unhealthy tunnels; repeated failures are flagged
  *needs attention* and can fire a **webhook alert**.

---

## 🚀 How it works

```
   1. Upload profiles      2. Connect the fleet       3. Operate & automate
   ────────────────        ──────────────────         ─────────────────────
   Drop .ovpn files   →    One isolated exit per  →   Map, metrics, scripts,
   into Connections        profile comes online       schedules, alerts — live
```

Under the hood, each profile runs a **worker** = a gluetun tunnel container + an
app container that shares its network namespace, so **all** of that app's traffic
exits through the tunnel. The controller orchestrates every worker and streams
everything back to your browser. See [Architecture](#-architecture) for the full
picture.

---

## 🏁 Quickstart

Flotilla runs anywhere Docker does.

```bash
cd c2
cp .env.example .env
# set a strong control token (macOS shown; on Linux drop the '')
sed -i '' "s/change-me/$(openssl rand -hex 24)/" .env
docker compose -p mvpn up -d --build
```

Open **http://127.0.0.1:8088**, go to **Settings**, paste the token from `.env`, then:

1. **Connections → drop your `.ovpn` files** (one exit per file).
2. **Connect all** — a worker per profile comes up; exit IPs auto-populate.
3. **Run script** → type a command, **Run on all connected**, and watch each exit
   stream its output live.

No real VPN provider handy? [`test-lab/`](#-test-lab--self-contained-demo) spins up
throwaway OpenVPN servers so you can see the isolation end-to-end.

---

## 🧩 Architecture

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
activity, metrics, schedules, job history) is persisted there too.

---

## 🔌 API & integrations

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
| `GET  /api/jobs`                        | recent job history (label, targets, status)                     |
| `GET  /api/jobs/<id>/stream`            | **SSE** live job output (replays + follows)                     |
| `POST /api/jobs/<id>/cancel`            | kill the job's processes (TERM, then KILL)                      |
| `GET  /api/metrics`                     | recent fleet metric points (for the charts)                     |
| `GET  /api/events`                      | recent activity                                                 |
| `GET/POST /api/settings`                | read / toggle auto-heal                                         |
| `GET  /api/proxy`                       | proxy-pool status: round-robin port + per-exit proxy ports      |
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

---

## ⚙️ Configuration

The controller is configured by environment variables (set in `c2/.env` or the
compose Environment tab):

| Variable             | Default | Purpose                                              |
|----------------------|---------|------------------------------------------------------|
| `CONTROL_TOKEN`      | —       | **required** — authorises every API call             |
| `TZ`                 | `UTC`   | timezone that schedule cron times are evaluated in   |
| `WEBHOOK_URL`        | unset   | JSON POST on auto-heal / give-up                     |
| `HEAL_INTERVAL`      | `20s`   | watchdog tick                                        |
| `HEAL_GRACE`         | `120s`  | how long an unhealthy tunnel is tolerated            |
| `HEAL_MAX_RESTARTS`  | `3`     | restarts within the window before giving up          |
| `HEAL_WINDOW`        | `900s`  | restart-count window                                 |
| `PROXY_POOL`         | `on`    | expose each exit as an HTTP proxy + round-robin front |
| `PROXY_PORT_BASE`    | `12000` | first host port for per-exit proxies (one per exit)  |
| `PROXY_RR_PORT`      | `18080` | round-robin proxy port (published on 127.0.0.1)      |

### Auto-heal

A watchdog reconnects exits that are meant to be up but dropped or went unhealthy.
Each connection has a **desired state** (set by Connect/Disconnect), so a manual
Disconnect is never overridden. Past `HEAL_MAX_RESTARTS` within `HEAL_WINDOW`, the
connection is flagged **needs attention** until you reconnect it.

---

## 🔐 Security & trust

The controller **mounts the Docker socket** (root-equivalent) and runs the
scripts you submit, so treat it as privileged infrastructure:

- Binds to `127.0.0.1` only; **every API call requires `CONTROL_TOKEN`.**
- **Never** expose port 8088 to the internet directly. For remote access use an
  SSH tunnel (`ssh -L 8088:127.0.0.1:8088 user@host`) or an authenticating proxy
  (e.g. Cloudflare Access).
- Profiles contain private keys and live only in the `mvpn-profiles` volume —
  never in git (`.gitignore` enforces this).
- **Kill-switch firewall** ensures a dropped tunnel fails closed, not open.

### Deploying on a server (Dokploy)

Use a **Docker Compose** service (not a Swarm "Application" — Swarm blocks the
`NET_ADMIN` / `/dev/net/tun` the tunnels need). Paste `c2/compose.yaml`, set
`CONTROL_TOKEN` in the Environment tab, deploy, and reach the panel over SSH.
Do not attach a public domain to it.

---

## 🧪 `test-lab/` — self-contained demo

`test-lab/` spins up throwaway OpenVPN servers so you can see the isolation
without a real provider. `gen-pki.sh` mints a separate CA per tunnel; generated
keys are git-ignored. Not needed to use Flotilla.

---

## 🗺️ Roadmap

- **SOCKS5 proxies** — alongside today's HTTP proxy pool, for tools that need SOCKS.
- WireGuard support · bulk `.zip` import (auto-named by country) ·
  RBAC + audit log · Prometheus metrics.

---

## 🧱 Built with

**Flask** · **docker-py** · **DragonflyDB** (Redis-compatible) · **gluetun** ·
a Debian worker image · and a dependency-free vanilla-JS single-page UI.

<div align="center">

---

If Flotilla is useful to you, **star the repo** ⭐ and
[open an issue](https://github.com/amithalder21/vpn-controller/issues) with ideas or bugs.

</div>
