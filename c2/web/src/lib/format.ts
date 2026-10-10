export function fmtBytes(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "—";
  if (n < 1024) return `${Math.round(n)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function fmtRate(bytesPerSec: number | null | undefined): string {
  if (bytesPerSec == null || isNaN(bytesPerSec)) return "0 B/s";
  return `${fmtBytes(bytesPerSec)}/s`;
}

export function fmtUptime(startedAt?: string | null): string {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  if (isNaN(start)) return "—";
  let s = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${s}s`;
}

export function fmtTime(epochOrIso?: number | string | null): string {
  if (epochOrIso == null) return "";
  const t = typeof epochOrIso === "number" ? epochOrIso * 1000 : new Date(epochOrIso).getTime();
  if (isNaN(t)) return "";
  return new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtRelative(epoch?: number | null): string {
  if (!epoch) return "";
  const diff = Math.floor(Date.now() / 1000 - epoch);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
