# Flotilla web

The Flotilla dashboard — a React + Vite + TypeScript + Tailwind SPA that talks
to the Flask controller's `/api/*` endpoints. This replaces the former
single-file vanilla UI.

## Stack

- **React 18 + Vite + TypeScript**
- **Tailwind CSS** with a token-based theme (light + auto dark via
  `prefers-color-scheme`)
- **shadcn/ui-style primitives** (Radix under the hood) in `src/components/ui`
- **TanStack Query** for API polling, **Recharts** for charts

## Develop

```bash
cd web
npm install
npm run dev     # http://localhost:5173, /api proxied to the controller on :8088
```

The controller must be running (see `../compose.yaml`). Enter the control token
on first load; it is stored in `localStorage` only.

## Build

```bash
npm run build
```

Vite builds to `../controller/static` with `base: /static/`, so the existing
Flask controller serves the SPA unchanged — `index.html` at `/`, assets under
`/static/assets/`, and `mapdata.json` (kept in `public/`) at `/static/`. The
controller bind-mounts `controller/static`, so a rebuilt bundle is live on
browser reload with no image rebuild.

## Layout

- `src/lib/` — API client, types, query hooks, formatters, toast store
- `src/components/ui/` — reusable primitives (button, card, sheet, …)
- `src/components/` — shared app pieces (Sidebar, charts, WorldMap, …)
- `src/views/` — one file per view (Overview, Connections, Run, Probe,
  Schedules, Activity, Settings) plus the drawers
