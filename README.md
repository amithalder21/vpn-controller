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
| `mvpn-<p>-app`   | shares the vpn container's network; your commands run here              |

```
                       ┌─────────────── controller (web UI + API) ───────────────┐
                       │   mounts /var/run/docker.sock, creates workers on demand  │
                       └──────┬───────────────────┬───────────────────┬───────────┘
                     worker A │           worker B │          worker C │
                   ┌──────────┴─────┐   ┌──────────┴─────┐   ┌─────────┴──────┐
                   │ vpn (gluetun)  │   │ vpn (gluetun)  │   │ vpn (gluetun)  │
                   │ app  ◄shares   │   │ app  ◄shares   │   │ app  ◄shares   │
                   └──────┬─────────┘   └──────┬─────────┘   └──────┬─────────┘
                       tunnel A             tunnel B             tunnel C
```

Because each app container shares its vpn container's network stack
(`network_mode: container:<vpn>`), **all** of its traffic exits through that VPN,
and the tunnels stay independent even if they use overlapping subnets.

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
| `POST /api/exec`                    | `{"command":"...","targets":"all","timeout":60}` run a command fleet-wide |

```bash
TOK=$(grep -o '[0-9a-f]\{48\}' c2/.env)
curl -s -X POST -H "X-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"command":"curl -s https://ifconfig.co/json","targets":"all"}' \
  http://127.0.0.1:8088/api/exec | jq
```

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
