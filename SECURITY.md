# Security Policy

Flotilla controls a fleet of VPN tunnels and **mounts the Docker socket**
(root-equivalent on the host), so security reports are taken seriously.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's **Report a vulnerability** button on the
[Security tab](https://github.com/amithalder21/flotilla/security/advisories/new)
(Security → Advisories → *Report a vulnerability*). This opens a private
advisory visible only to the maintainers.

Please include:

- a description of the issue and its impact,
- steps to reproduce (a proof of concept if you have one),
- affected version / commit, and
- any suggested remediation.

You can expect an initial acknowledgement within a few days. Once a fix is
ready we'll coordinate disclosure and credit you (unless you prefer to remain
anonymous).

## Scope & expectations

Flotilla is **single-operator and localhost-only by default**. It is designed to
run behind a trust boundary (your own machine, a LAN, or an SSH tunnel) — see
[Security & trust](README.md#security--trust) in the README.

In scope:

- Authentication/authorization bypass of the control API (`CONTROL_TOKEN`).
- Command or container escapes from a worker to the host.
- Leaks where tunnelled traffic can egress untunnelled (kill-switch bypass).
- Token, profile (private key), or credential exposure.

Out of scope:

- Issues that require already exposing the controller publicly without a proxy
  (explicitly advised against).
- Vulnerabilities in third-party images (gluetun, DragonflyDB) — report those
  upstream; we'll happily bump versions.
- Misuse of the tool itself (Flotilla is for authorized testing and research).
