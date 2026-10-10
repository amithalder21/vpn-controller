#!/bin/bash
# latency.sh — connection + TTFB breakdown from each exit, averaged over N runs.
# Run on all connected to get a latency map of your service across regions.
#
# Edit TARGET / N (or set them as env vars).
set -u
TARGET="${TARGET:-https://example.com}"
N="${N:-5}"

echo "== $TARGET  (avg of $N) =="
tmp=$(mktemp)
for _ in $(seq 1 "$N"); do
  curl -o /dev/null -sS --max-time 20 \
    -w '%{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}\n' \
    "$TARGET" >> "$tmp" 2>/dev/null || echo "0 0 0 0 0" >> "$tmp"
done

awk '{dns+=$1; con+=$2; tls+=$3; ttfb+=$4; tot+=$5; n++}
     END{ if(!n){print "  no samples"; exit}
          printf "  dns=%.3fs  connect=%.3fs  tls=%.3fs  ttfb=%.3fs  total=%.3fs  (avg, n=%d)\n",
                 dns/n, con/n, tls/n, ttfb/n, tot/n, n }' "$tmp"
p50=$(awk '{print $5}' "$tmp" | sort -n | awk '{a[NR]=$1} END{if(NR)printf "%.3f", a[int((NR+1)/2)]}')
mn=$(awk '{print $5}' "$tmp" | sort -n | head -1)
mx=$(awk '{print $5}' "$tmp" | sort -n | tail -1)
echo "  p50=${p50}s  min=${mn}s  max=${mx}s"
rm -f "$tmp"
