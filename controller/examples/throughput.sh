#!/bin/bash
# throughput.sh — download speed from each exit.
# While this runs, watch Overview → Live throughput and the per-exit
# Throughput column fill in with the real rate.
#
# Edit BYTES / URL (or set them as env vars). Default pulls from a public
# Cloudflare speed endpoint; point URL at your own asset to test your CDN.
set -u
BYTES="${BYTES:-10000000}"                              # 10 MB
URL="${URL:-https://speed.cloudflare.com/__down?bytes=$BYTES}"

echo "== download $URL =="
res=$(curl -o /dev/null -sS --max-time 60 \
      -w '%{speed_download} %{size_download} %{time_total}' "$URL" 2>/dev/null) \
  || { echo "  download failed"; exit 1; }

set -- $res
bps=$1; size=$2; t=$3
mbs=$(awk  -v b="$bps"  'BEGIN{printf "%.2f", b/1048576}')
mbit=$(awk -v b="$bps"  'BEGIN{printf "%.1f", b*8/1000000}')
mb=$(awk   -v s="$size" 'BEGIN{printf "%.1f", s/1048576}')
echo "  ${mbs} MB/s  (${mbit} Mbit/s)   downloaded ${mb} MB in ${t}s"
