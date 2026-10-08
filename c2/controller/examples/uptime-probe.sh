#!/bin/bash
# uptime-probe.sh — health check from each exit.
# Great on a Schedule (e.g. every 5 min). A failed region exits non-zero so
# it shows red in the job output; set WEBHOOK_URL on the controller to be
# alerted when a region can't reach your service.
#
# Edit TARGET (or set it as an env var).
set -u
TARGET="${TARGET:-https://example.com/health}"

geo=$(curl -fsS --max-time 10 https://ifconfig.co/country 2>/dev/null || echo "?")
out=$(curl -fsS -o /dev/null --max-time 15 -w '%{http_code} %{time_total}' "$TARGET" 2>/dev/null)
rc=$?

if [ "$rc" -eq 0 ]; then
  set -- $out
  echo "UP    $TARGET  http=$1  ${2}s  via $geo"
else
  echo "DOWN  $TARGET  (curl rc=$rc)  via $geo"
  exit 1
fi
