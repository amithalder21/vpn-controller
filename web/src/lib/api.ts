const TOKEN_KEY = "mvpn-token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}
export function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(
  method: string,
  path: string,
  body?: unknown,
  isForm = false,
): Promise<T> {
  const headers: Record<string, string> = { "X-Token": getToken() };
  const opts: RequestInit = { method, headers };
  if (body && isForm) {
    opts.body = body as BodyInit;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError((data as any)?.error || res.statusText, res.status);
  }
  return data as T;
}

/** EventSource URL with the token as a query param (SSE can't set headers). */
export function sseUrl(path: string): string {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}token=${encodeURIComponent(getToken())}`;
}
