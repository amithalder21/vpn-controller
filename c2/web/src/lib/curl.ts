export interface CurlParsed {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: string;
  follow: boolean;
}

export function looksLikeCurl(s: string): boolean {
  return /^\s*curl\b/i.test(s);
}

/** Tokenize a shell-ish curl command: honours ' ' and " " quoting, backslash
 *  escapes, line continuations, and `$'...'` quoting. */
function tokenize(input: string): string[] {
  const s = input.replace(/\\\r?\n/g, " ").replace(/\r?\n/g, " ");
  const tokens: string[] = [];
  let i = 0;
  const n = s.length;
  const ws = (c: string) => c === " " || c === "\t";
  while (i < n) {
    while (i < n && ws(s[i])) i++;
    if (i >= n) break;
    let tok = "";
    while (i < n && !ws(s[i])) {
      const c = s[i];
      if (c === "$" && (s[i + 1] === "'" || s[i + 1] === '"')) {
        i++; // drop ANSI-C / locale quote prefix
        continue;
      }
      if (c === "'") {
        i++;
        while (i < n && s[i] !== "'") tok += s[i++];
        i++;
      } else if (c === '"') {
        i++;
        while (i < n && s[i] !== '"') {
          if (s[i] === "\\" && "\"\\$`".includes(s[i + 1])) {
            tok += s[i + 1];
            i += 2;
          } else {
            tok += s[i++];
          }
        }
        i++;
      } else if (c === "\\") {
        if (i + 1 < n) {
          tok += s[i + 1];
          i += 2;
        } else i++;
      } else {
        tok += c;
        i++;
      }
    }
    tokens.push(tok);
  }
  return tokens;
}

const DATA_FLAGS = new Set(["-d", "--data", "--data-raw", "--data-ascii", "--data-binary", "--data-urlencode"]);
// value-taking flags we ignore but must skip the value of, so it isn't read as the URL
const SKIP_VALUE = new Set([
  "-o", "--output", "-w", "--write-out", "-m", "--max-time", "--connect-timeout",
  "--retry", "-x", "--proxy", "--cacert", "--cert", "--key", "--resolve",
  "-T", "--upload-file", "--limit-rate", "-C", "--continue-at",
]);

export function parseCurl(input: string): CurlParsed | null {
  if (!looksLikeCurl(input)) return null;
  const toks = tokenize(input);
  let i = toks[0]?.toLowerCase() === "curl" ? 1 : 0;

  let method = "";
  let url = "";
  const headers: Record<string, string> = {};
  const data: string[] = [];
  let follow = false;
  let getFlag = false;
  let user = "";

  const peekNext = () => toks[i + 1] ?? "";

  for (; i < toks.length; i++) {
    const t = toks[i];
    if (!t) continue;

    if (t === "-X" || t === "--request") { method = peekNext().toUpperCase(); i++; continue; }
    if (t.startsWith("-X") && t.length > 2) { method = t.slice(2).toUpperCase(); continue; }

    if (t === "-H" || t === "--header") {
      const h = peekNext(); i++;
      const idx = h.indexOf(":");
      if (idx > 0) headers[h.slice(0, idx).trim()] = h.slice(idx + 1).trim();
      continue;
    }

    if (DATA_FLAGS.has(t)) { data.push(peekNext()); i++; continue; }
    if (t.startsWith("--data=")) { data.push(t.slice(7)); continue; }

    if (t === "-u" || t === "--user") { user = peekNext(); i++; continue; }
    if (t === "-A" || t === "--user-agent") { headers["User-Agent"] = peekNext(); i++; continue; }
    if (t === "-b" || t === "--cookie") { headers["Cookie"] = peekNext(); i++; continue; }
    if (t === "-e" || t === "--referer") { headers["Referer"] = peekNext(); i++; continue; }
    if (t === "--url") { url = peekNext(); i++; continue; }

    if (t === "-L" || t === "--location") { follow = true; continue; }
    if (t === "-G" || t === "--get") { getFlag = true; continue; }
    if (t === "-I" || t === "--head") { method = method || "HEAD"; continue; }

    if (SKIP_VALUE.has(t)) { i++; continue; }

    if (t.startsWith("-")) {
      // combined short booleans like -sL
      if (/^-[a-zA-Z]+$/.test(t) && t.length > 2) {
        if (t.includes("L")) follow = true;
        if (t.includes("I")) method = method || "HEAD";
        if (t.includes("G")) getFlag = true;
      }
      continue; // ignore other flags (-k, --compressed, -s, -v, …)
    }

    if (!url) url = t; // positional → URL
  }

  if (!url) return null;
  if (!/^https?:\/\//i.test(url)) url = "https://" + url.replace(/^\/\//, "");

  let body = data.join("&");
  if (!method) method = body && !getFlag ? "POST" : "GET";
  if (user && !headers["Authorization"]) {
    try {
      headers["Authorization"] = "Basic " + btoa(user);
    } catch { /* non-latin creds */ }
  }
  if (getFlag && body) {
    url += (url.includes("?") ? "&" : "?") + body;
    body = "";
    method = "GET";
  }

  return { method, url, headers, body, follow };
}
