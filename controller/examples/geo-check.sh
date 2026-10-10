#!/bin/bash
# geo-check.sh — what each exit sees.
# Prints this exit's geo identity, then how a URL is served from here
# (status, a content fingerprint, localization, CDN/cache headers).
# Run on all connected to compare regions side by side: exits whose
# body-sha differs are being served different content (geo variance).
#
# Edit TARGET (or set it as an env var before running).
set -u
TARGET="${TARGET:-https://example.com}"

echo "== exit identity =="
curl -fsS --max-time 15 https://ifconfig.co/json 2>/dev/null \
  | jq -r '"  \(.country // "?") (\(.country_iso // "??"))  ip=\(.ip)  isp=\(.asn_org // "?")"' \
  || echo "  identity lookup failed"

echo "== $TARGET =="
body=$(mktemp); hdr=$(mktemp)
curl -sS -A flotilla-qa --max-time 20 -o "$body" -D "$hdr" \
     -w '  status=%{http_code}  final=%{url_effective}  time=%{time_total}s\n' \
     "$TARGET" 2>/dev/null || echo "  request failed"
echo "  body-sha=$(sha1sum "$body" 2>/dev/null | cut -c1-12)  bytes=$(wc -c < "$body" 2>/dev/null | tr -d ' ')"
grep -oiE 'lang="[a-z-]+"' "$body" 2>/dev/null | head -1 | sed 's/^/  html /'
grep -iE '^(cf-ray|x-served-by|x-cache|x-amz-cf-pop|age|server):' "$hdr" 2>/dev/null | sed 's/^/  /'
rm -f "$body" "$hdr"
