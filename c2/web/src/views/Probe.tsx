import { useState } from "react";
import { Radar } from "lucide-react";
import { api } from "@/lib/api";
import { toast, useWorkers } from "@/lib/hooks";
import type { ProbeResult, ProbeRow } from "@/lib/types";
import { Card, CardBody, CardHeader, CardSub, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { CountryChip, DiffBadge, EmptyState } from "@/components/common";
import { fmtBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ProbeResponseSheet } from "./ProbeResponseSheet";

const METHODS = ["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"];

export function Probe() {
  const { data: workers = [] } = useWorkers();
  const [method, setMethod] = useState("GET");
  const [url, setUrl] = useState("");
  const [headers, setHeaders] = useState("");
  const [body, setBody] = useState("");
  const [baseline, setBaseline] = useState(false);
  const [follow, setFollow] = useState(true);
  const [timeout, setTimeoutS] = useState(20);
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<ProbeRow | null>(null);

  const online = workers.filter((w) => w.exists && w.vpn === "running" && w.health === "healthy").length;

  function parseHeaders() {
    const out: Record<string, string> = {};
    headers.split("\n").forEach((l) => {
      const i = l.indexOf(":");
      if (i < 1) return;
      const k = l.slice(0, i).trim();
      if (k) out[k] = l.slice(i + 1).trim();
    });
    return out;
  }

  async function run() {
    if (!url.trim()) {
      toast("Enter a URL to probe", "err");
      return;
    }
    setBusy(true);
    try {
      const r = await api<ProbeResult>("POST", "/api/probe", {
        url: url.trim(),
        method,
        headers: parseHeaders(),
        body,
        baseline,
        follow,
        timeout,
      });
      r.req = { method, url: r.url };
      setResult(r);
    } catch (e: any) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  const allRows = result ? [...result.rows, ...(result.direct ? [result.direct] : [])] : [];
  const outliers = result?.rows.filter((r) => r.diff === "outlier").length ?? 0;
  const errs = result?.rows.filter((r) => r.diff === "error").length ?? 0;
  const summary = result
    ? result.all_unique && result.count - errs > 1
      ? `${result.count} exits · all responses unique · ${errs} unreachable`
      : `${result.count} exits · ${outliers} differ · ${errs} unreachable`
    : "";

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Probe across the fleet</CardTitle>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground tabular">
            {online ? `${online} online exit${online > 1 ? "s" : ""}` : "no online exits"}
          </span>
        </CardHeader>
        <CardBody className="space-y-3">
          <p className="text-[12.5px] text-muted-foreground">
            Send one request through every online exit at once and compare the responses. Rows that differ from the majority
            are flagged — a fast way to spot geo-blocking, WAF behaviour, or region-specific content.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={method} onChange={(e) => setMethod(e.target.value)} className="w-28">
              {METHODS.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </Select>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://target.example.com/path"
              className="min-w-[260px] flex-1"
              onKeyDown={(e) => e.key === "Enter" && run()}
            />
            <Button variant="primary" onClick={run} disabled={busy}>
              <Radar /> {busy ? "Running…" : "Run across fleet"}
            </Button>
          </div>
          <details>
            <summary className="cursor-pointer text-[12.5px] text-muted-foreground">Headers &amp; body (optional)</summary>
            <div className="mt-2 flex flex-wrap gap-3">
              <div className="min-w-[240px] flex-1">
                <div className="mb-1 text-[11.5px] text-muted-foreground">Headers — one per line, <span className="font-mono">Name: value</span></div>
                <Textarea value={headers} onChange={(e) => setHeaders(e.target.value)} className="min-h-[72px]" placeholder={"User-Agent: Mozilla/5.0\nAccept-Language: en-US"} />
              </div>
              <div className="min-w-[240px] flex-1">
                <div className="mb-1 text-[11.5px] text-muted-foreground">Request body (POST/PUT/PATCH)</div>
                <Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-[72px]" />
              </div>
            </div>
          </details>
          <div className="flex flex-wrap items-center gap-5 text-[12.5px] text-muted-foreground">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" className="size-[15px] accent-accent" checked={baseline} onChange={(e) => setBaseline(e.target.checked)} />
              Direct (no-VPN) baseline row
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" className="size-[15px] accent-accent" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
              Follow redirects
            </label>
            <label className="flex items-center gap-2">
              Timeout
              <input type="number" min={1} max={60} value={timeout} onChange={(e) => setTimeoutS(+e.target.value || 20)} className="h-8 w-16 rounded-md border border-input bg-background px-2 text-sm" />
              s
            </label>
          </div>
          <p className="text-[11.5px] text-muted-foreground">Click any result row to inspect that exit's full response — status line, headers, and body.</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Results</CardTitle>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground tabular">{summary}</span>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border/70 text-left text-2xs uppercase tracking-wider text-muted-foreground">
                {["Exit", "Country", "Status", "Size", "Type", "Server", "Body hash", "Time", "Diff"].map((h) => (
                  <th key={h} className={cn("px-2 py-2.5 font-semibold", h === "Time" && "text-right")}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!allRows.length && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState>Enter a URL and run it across the fleet to see per-exit responses here.</EmptyState>
                  </td>
                </tr>
              )}
              {allRows.map((r, i) => (
                <tr
                  key={r.exit + i}
                  onClick={() => setOpen({ ...r, ...({} as any) })}
                  className={cn(
                    "cursor-pointer border-b border-border/60 text-[13px] transition-colors last:border-0 hover:bg-accent/5",
                    r.diff === "outlier" && "bg-warn-bg/40",
                    r.error && "text-muted-foreground",
                  )}
                >
                  <td className="px-2 py-2.5 font-mono">{r.exit}</td>
                  <td className="px-2 py-2.5"><CountryChip iso={r.country_iso} country={r.country} /></td>
                  {r.error ? (
                    <td colSpan={5} className="px-2 py-2.5 text-muted-foreground">{r.error}</td>
                  ) : (
                    <>
                      <td className="px-2 py-2.5 tabular">{r.status}</td>
                      <td className="px-2 py-2.5 tabular">{fmtBytes(r.size)}</td>
                      <td className="px-2 py-2.5 text-muted-foreground">{r.ctype}</td>
                      <td className="px-2 py-2.5 text-muted-foreground">{r.server}</td>
                      <td className="px-2 py-2.5 font-mono text-muted-foreground">{r.hash}</td>
                    </>
                  )}
                  <td className="px-2 py-2.5 text-right tabular">{r.ms != null ? `${r.ms}ms` : ""}</td>
                  <td className="px-2 py-2.5"><DiffBadge diff={r.diff} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <ProbeResponseSheet row={open} req={result?.req} onClose={() => setOpen(null)} />
    </div>
  );
}
