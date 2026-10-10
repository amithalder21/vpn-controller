# Contributing to Flotilla

Thanks for your interest in improving Flotilla! Issues, ideas, and pull
requests are all welcome.

## Ground rules

- Flotilla is a tool for **authorized testing, monitoring, and research**.
  Contributions that primarily enable abuse (ban evasion, credential stuffing,
  ToS-violating scraping, fraud) won't be accepted.
- By contributing, you agree your contributions are licensed under the project's
  [GNU AGPL-3.0](LICENSE).
- Be respectful — see the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting set up

You need **Docker**. The whole stack comes up with one command:

```bash
./setup.sh
```

For live UI work, run the Vite dev server (it proxies `/api` to the controller):

```bash
cd web && npm install && npm run dev   # http://localhost:5173
```

Project layout:

| Path          | What it is                                        |
|---------------|---------------------------------------------------|
| `controller/` | Flask backend + JSON API (`app.py`) and Dockerfile |
| `web/`        | React + Vite + TypeScript dashboard               |
| `worker-app/` | the per-exit worker image                         |
| `compose.yaml`| the stack (controller + DragonflyDB + workers)    |
| `docs/`       | design notes                                      |
| `test-lab/`   | throwaway OpenVPN servers for local testing       |

See [`web/README.md`](web/README.md) for the frontend details.

## Making a change

1. **Open an issue first** for anything non-trivial, so we can agree on the
   approach before you invest time.
2. Create a branch, keep the change focused, and match the surrounding style.
   - Backend: Python, standard library where reasonable; keep endpoints small.
   - Frontend: TypeScript; `npm run build` must pass (`tsc --noEmit` is part of it).
3. **Test your change.** For the UI, verify in the browser against a running
   controller. For the API, exercise the affected endpoint.
4. Update docs (README / `web/README.md`) when you change behavior or add a
   feature or endpoint.

## Submitting a pull request

- Describe **what** changed and **why**; link the issue it closes.
- Keep PRs reviewable — one logical change per PR.
- Make sure the app still builds and runs: `docker compose -p mvpn up -d --build`.

## Reporting bugs & requesting features

Use the issue templates. For **security vulnerabilities**, do **not** open a
public issue — follow [SECURITY.md](SECURITY.md).
