#!/usr/bin/env bash
# Flotilla — one-click setup.
# Builds the stack (controller + UI + DragonflyDB) and brings it up.
# Safe to re-run: it reuses an existing token and existing data volumes.
set -euo pipefail

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

bold "Flotilla setup"

# ---- 1. prerequisites ----
command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker Desktop (or OrbStack) first: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop and re-run this script."
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  die "Docker Compose not found. Update Docker Desktop (it bundles Compose v2)."
fi
ok "Docker is ready"

# ---- 2. control token (.env) ----
gen_token() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 24
  else head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}
if [ -f .env ] && grep -q '^CONTROL_TOKEN=.\+' .env; then
  TOKEN="$(grep '^CONTROL_TOKEN=' .env | head -1 | cut -d= -f2-)"
  ok "Reusing existing control token from .env"
else
  TOKEN="$(gen_token)"
  # preserve any other .env lines, replace/append CONTROL_TOKEN
  if [ -f .env ]; then grep -v '^CONTROL_TOKEN=' .env > .env.tmp || true; mv .env.tmp .env; fi
  echo "CONTROL_TOKEN=$TOKEN" >> .env
  ok "Generated a new control token and wrote it to .env"
fi

# ---- 3. build + launch ----
bold "Building images (first run compiles the UI — this can take a few minutes)…"
$DC -p mvpn up -d --build

# ---- 4. wait for the controller ----
printf "Waiting for the controller to come up"
URL="http://127.0.0.1:8088"
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null "$URL/" 2>/dev/null; then printf "\n"; ok "Controller is up"; break; fi
  printf "."; sleep 2
  [ "$i" -eq 60 ] && { printf "\n"; die "Controller did not respond in time. Check logs: $DC -p mvpn logs controller"; }
done

# ---- 5. done ----
echo
bold "Flotilla is running."
echo "  Open:         $URL"
echo "  Control token: $TOKEN"
echo
echo "Paste that token when the dashboard asks for it (stored in your browser only)."
echo "Next: open Connections and drop your .ovpn profiles to add exits."
echo
echo "Manage it with:"
echo "  $DC -p mvpn logs -f controller     # view logs"
echo "  $DC -p mvpn down                   # stop (data volumes are kept)"
