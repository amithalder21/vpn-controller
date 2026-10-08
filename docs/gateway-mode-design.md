# Design: Gateway mode — route local system traffic through a chosen exit

Status: **Draft for review** · Owner: TBD · Target: post-proxy-pool

## 1. Problem & goal

Today Flotilla can route **proxy-aware** traffic through any exit (the HTTP
proxy pool: per-exit `127.0.0.1:<port>` + round-robin `127.0.0.1:18080`). That
covers browsers, `curl`, Burp, and most dev tools.

**Goal:** let an operator route **all** traffic from their own machine (or a
device/LAN) through a chosen exit — including apps that don't honor a proxy,
and ideally UDP — and switch the active exit on demand from the dashboard.

Think "a normal always-on VPN on my laptop, where I flip the egress country in
Flotilla."

### Non-goals
- Multi-tenant/public VPN service. Flotilla stays **single-operator, behind a
  trust boundary** (LAN / SSH / WG), never exposed publicly.
- Per-connection rotation for the *system* path. Gateway mode **pins** one exit
  per session (switch on demand); round-robin stays a proxy-pool feature for
  QA/research.

## 2. Terminology

| Term | Meaning |
|------|---------|
| **Proxy mode** | App points at an HTTP/SOCKS proxy. Already shipped. |
| **Gateway mode** | OS-level/transparent routing of all traffic through an exit. This doc. |
| **Exit** | One profile's worker = gluetun tunnel + app container sharing its netns. |
| **Active exit** | The exit gateway-mode traffic currently egresses through. |

## 3. Current building blocks (reuse)

- Each exit's gluetun has an HTTP proxy on `:8888` in its netns, egressing via
  that tunnel; reachable from the controller over the Docker network at
  `<vpn-ip>:8888`, and published on host loopback per exit.
- The controller already runs a round-robin TCP front; the same "pick an exit,
  relay into its netns" machinery generalizes.
- Kill-switch firewall (gluetun) means a dropped tunnel fails **closed**.

## 4. Options

### Option A — Client-side TUN over the proxy pool (small, works on any client)

Run a userspace tunnel on the operator's machine (`sing-box`, `tun2socks`, or
`hev-socks5-tunnel`) that creates a local `tun` interface and forwards every
packet into Flotilla's proxy.

```
  [ all local apps ] → tun0 → sing-box → (HTTP/SOCKS) → Flotilla exit → Internet
       (the user's machine)                  127.0.0.1:18080 or :<exit port>
```

- **Server side:** add **SOCKS5** per exit (TUN helpers prefer SOCKS; also helps
  tools that don't speak HTTP proxy). gluetun offers Shadowsocks, not raw SOCKS,
  so run a tiny SOCKS server (e.g. `microsocks`) in each app container, or a
  SOCKS front on the controller mirroring the HTTP round-robin.
- **Client side:** ship a `sing-box` config + `flotilla-gateway.sh up|down` that
  brings the tun up, sets routes, and restores on exit. Switching exit = restart
  pointed at a different port.
- **Pros:** no kernel routing on the controller; works from macOS/Linux/Windows;
  low risk; testable by the user immediately.
- **Cons:** requires a client helper install; UDP depends on the helper; "system
  VPN" UX is a CLI toggle, not a dashboard switch for the device itself.

### Option B — WireGuard gateway mode (controller as router) — best UX

The controller runs a **WireGuard server**. The operator's device holds **one**
WG config pointing at the controller. In the UI they choose the **active exit**;
the controller policy-routes WG client traffic out through that exit's tunnel.

```
  [ device ] --WireGuard--> [ controller wg0 ] --policy route--> [ active exit netns ] --> Internet
     one static config          NAT + ip rule            gluetun tunnel (kill-switch)
             ▲
             └──── switch active exit from the dashboard (no client change)
```

- **Pros:** real device-level VPN; switch country from the dashboard with no
  client reconfig; UDP + all traffic; mobile-friendly (WG apps everywhere).
- **Cons:** the controller becomes an L3 router (NAT, `ip rule`/`nftables`,
  `net.ipv4.ip_forward`), needs `NET_ADMIN` + a published WG UDP port, and key
  management. Most code and the widest attack surface — must stay private.

## 5. Detailed design — Option B (the build)

### 5.1 Topology & routing
- Controller container (or a dedicated `gateway` sidecar) gets `NET_ADMIN`,
  `/dev/net/tun`, `sysctl net.ipv4.ip_forward=1`, and joins `mvpn-net`.
- `wg0` listens on UDP (default `51820`), published on host (loopback or LAN per
  deployment). Each operator device = one WG **peer**.
- The gateway forwards packets from `wg0` into the **active exit's netns**. Two
  viable mechanisms:
  1. **Relay into the exit's gluetun** via its HTTP/SOCKS proxy using an
     in-gateway `tun2socks` (userspace; simplest, no per-exit kernel plumbing).
     Packet path: `wg0 → tun2socks → exit proxy (:8888/:1080) → tunnel`.
  2. **Kernel policy routing** into the exit netns (fastest, most complex): add
     a veth/route from the gateway into the chosen vpn container's netns and
     `ip rule` mark WG traffic to it. More moving parts; revisit if throughput
     demands it.
  **Recommendation:** start with (1) — reuses the proxy pool, no per-exit kernel
  changes, switching exit = repoint tun2socks. Treat (2) as an optimization.

### 5.2 Active-exit selection
- New stored setting `gateway.active_exit` (Dragonfly). Changing it repoints the
  gateway's upstream (tun2socks → new exit's proxy). Validated against a healthy,
  running exit; if the active exit goes unhealthy, optionally **auto-failover**
  to another (reuse auto-heal signals) or **fail closed** (configurable).

### 5.3 DNS
- Push a DNS resolver to WG clients that also egresses via the exit (gluetun's
  DNS-over-TLS inside the netns), so DNS doesn't leak outside the tunnel.
  Validate with the existing leak-test, extended for DNS.

### 5.4 Kill-switch semantics
- If the active exit drops: default **fail closed** (drop WG-forwarded traffic)
  so the device never leaks to the host's real IP. Surface this state in the UI.

### 5.5 Key management
- Generate the server keypair on first boot (store private key in the gateway
  volume, never in git). Each device peer: generate keypair, show the client
  config (QR for mobile) once. Store peer public keys + allowed-IPs in Dragonfly.
- Revoke = remove peer + reload wg.

## 6. API additions (sketch)

| Method & path | Does |
|---------------|------|
| `GET  /api/gateway`            | mode, active_exit, kill-switch policy, wg status |
| `POST /api/gateway`            | set `{active_exit, failover, enabled}` |
| `GET  /api/gateway/peers`      | list WG peers (name, pubkey, allowed-ip, last-seen) |
| `POST /api/gateway/peers`      | add a device → returns its client config (+ QR) |
| `DELETE /api/gateway/peers/<id>` | revoke a device |

## 7. UI additions
- New **Gateway** view: enable/disable, an **active-exit picker** (searchable,
  shows country/health), kill-switch + failover toggles, and a **Devices** list
  (add device → modal with the WG config + QR + copy).
- Overview/exit badges: mark the exit currently serving the gateway.

## 8. Security considerations
- Gateway mode listens for device traffic (WG UDP) — a real ingress. Keep it on
  LAN/loopback or require the device already be on a trusted network; document
  "never publish WG to the internet without intent."
- Controller gains `NET_ADMIN` + IP forwarding → broader blast radius. Consider a
  **separate `gateway` container** so the Flask controller keeps its current
  privileges and the router is isolated.
- Fail-closed by default; DNS through the tunnel; leak-test the gateway path.
- All of this stays gated behind a flag (`GATEWAY_MODE=off` by default).

## 9. Verification plan
Testable in CI / without a real host:
- Active-exit selection + validation, failover state machine, peer CRUD, config
  generation (wg config correctness), API shapes — unit tests.
- tun2socks upstream repointing logic (the "which exit" decision) — unit test,
  as done for the proxy round-robin.

Needs a real Docker host + kernel:
- WG handshake, IP forwarding, tun2socks data path, DNS-no-leak, kill-switch
  fail-closed, throughput. Documented as host-validation steps (same posture as
  the proxy pool, which couldn't be fully validated in the build environment).

## 10. Phased rollout
1. **Phase 0 (now):** SOCKS5 pool + client TUN helper + how-to (Option A). Gets
   system-wide routing working immediately with minimal risk.
2. **Phase 1:** `gateway` container + WG server + tun2socks to a **fixed** active
   exit; set/active-exit API + minimal UI. Fail-closed.
3. **Phase 2:** device peer management (add/revoke, QR), DNS-no-leak, auto-failover.
4. **Phase 3 (optional):** kernel policy-routing data path for throughput.

## 11. Open decisions
- Separate `gateway` container vs. extend the controller? (Lean: **separate**.)
- Default kill-switch on exit failure: fail-closed vs auto-failover? (Lean:
  **fail-closed**, failover opt-in.)
- WG only, or also client TUN helper shipped alongside? (Lean: **ship both** —
  helper now, WG as the polished path.)
- Expose gateway on loopback only (SSH-tunnelled) or LAN? (Deployment choice;
  default **loopback**.)

---

**Recommendation:** approve **Phase 0** to unblock system-wide routing this week
(low risk, reuses the proxy pool), and green-light **Phase 1** of WireGuard
gateway mode as the dashboard-switchable device VPN.
