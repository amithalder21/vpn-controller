import { useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Info, Power, RotateCw, ScrollText, Search, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { keys, toast, useWorkers } from "@/lib/hooks";
import type { Worker } from "@/lib/types";
import { CountryChip, Mono, StatusPill } from "@/components/common";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { ConnectionDrawer } from "./ConnectionDrawer";
import { LogsDrawer } from "./LogsDrawer";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "connected", label: "Connected" },
  { id: "attention", label: "Needs attention" },
  { id: "stopped", label: "Stopped" },
] as const;
type FilterId = (typeof FILTERS)[number]["id"];

function running(w: Worker) {
  return w.exists && w.vpn === "running";
}

export function Connections() {
  const qc = useQueryClient();
  const { data: workers = [] } = useWorkers();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<FilterId>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<string | null>(null);
  const [logsFor, setLogsFor] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  const refresh = () => qc.invalidateQueries({ queryKey: keys.workers });

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    return workers.filter((w) => {
      if (filter === "connected" && !(running(w) && w.health === "healthy")) return false;
      if (filter === "attention" && !(w.gaveup || (running(w) && w.health === "unhealthy"))) return false;
      if (filter === "stopped" && running(w)) return false;
      if (!term) return true;
      const hay = [w.name, w.ipinfo?.ip, w.ipinfo?.country, w.ipinfo?.org, ...(w.tags || [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(term);
    });
  }, [workers, q, filter]);

  async function act(name: string, action: string, note?: string) {
    setBusy((b) => new Set(b).add(name));
    if (note) toast(`${name}: ${note}`, "info", 1400);
    try {
      await api("POST", `/api/workers/${name}/${action}`);
    } catch (e: any) {
      toast(`${name}: ${e.message}`, "err");
    } finally {
      setBusy((b) => {
        const n = new Set(b);
        n.delete(name);
        return n;
      });
      refresh();
    }
  }

  async function bulk(action: string, verb: string) {
    const targets = selected.size ? [...selected] : undefined;
    try {
      const r = await api<Record<string, any>>("POST", `/api/bulk/${action}`, targets ? { targets } : {});
      const errs = Object.entries(r).filter(([, v]) => v && v.error);
      errs.length
        ? toast(errs.map(([k, v]) => `${k}: ${v.error}`).join("\n"), "err")
        : toast(`${verb} ${Object.keys(r).length} connection(s)`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }

  async function upload(files: FileList) {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    try {
      const r = await api<{ saved: string[] }>("POST", "/api/profiles", fd, true);
      toast(`Added ${r.saved.join(", ")}`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }

  function toggleSel(name: string) {
    setSelected((s) => {
      const n = new Set(s);
      n.has(name) ? n.delete(name) : n.add(name);
      return n;
    });
  }
  const allSel = rows.length > 0 && rows.every((w) => selected.has(w.name));

  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Connections</CardTitle>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular">
            {workers.length}
          </span>
          <div className="flex-1" />
          <Button variant="primary" size="sm" onClick={() => bulk("start", "Connected")}>
            Connect all
          </Button>
        </CardHeader>

        {/* filters */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border/70 bg-muted/40 px-4 py-2.5">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name, IP, country, org…"
              className="h-8 bg-card pl-8 text-[13px]"
            />
          </div>
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  "rounded-full border px-3 py-1 text-[12.5px] transition-colors",
                  filter === f.id
                    ? "border-accent bg-accent text-accent-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* selection bar */}
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-border/70 bg-accent/10 px-4 py-2.5 text-[13px]">
            <span className="font-medium">{selected.size} selected</span>
            <div className="flex-1" />
            <Button size="xs" variant="primary" onClick={() => bulk("start", "Connected")}>Connect</Button>
            <Button size="xs" onClick={() => bulk("stop", "Disconnected")}>Disconnect</Button>
            <Button size="xs" onClick={() => bulk("restart", "Reconnected")}>Reconnect</Button>
            <Button size="xs" onClick={() => bulk("shutdown", "Shut down")}>Shut down</Button>
            <Button size="xs" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
          </div>
        )}

        {/* table */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border/70 text-left text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="w-9 px-3 py-2.5">
                  <input
                    type="checkbox"
                    className="size-[15px] cursor-pointer accent-accent"
                    checked={allSel}
                    onChange={() =>
                      setSelected(allSel ? new Set() : new Set(rows.map((w) => w.name)))
                    }
                  />
                </th>
                <th className="px-2 py-2.5 font-semibold">Connection</th>
                <th className="px-2 py-2.5 font-semibold">Exit</th>
                <th className="px-2 py-2.5 font-semibold">Status</th>
                <th className="px-2 py-2.5 font-semibold">Proxy</th>
                <th className="px-2 py-2.5 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {!rows.length && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-[13px] text-muted-foreground">
                    {workers.length ? "No connections match the current filter." : "No connections yet — drop .ovpn files below to add one."}
                  </td>
                </tr>
              )}
              {rows.map((w) => {
                const on = running(w);
                const isBusy = busy.has(w.name);
                return (
                  <tr
                    key={w.name}
                    className="group border-b border-border/60 transition-colors last:border-0 hover:bg-muted/50"
                  >
                    <td className="px-3 py-2.5 align-middle">
                      <input
                        type="checkbox"
                        className="size-[15px] cursor-pointer accent-accent"
                        checked={selected.has(w.name)}
                        onChange={() => toggleSel(w.name)}
                      />
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      <button className="text-left" onClick={() => setDetail(w.name)}>
                        <div className="font-mono text-[13.5px] font-semibold">{w.name}</div>
                        <div className="mt-0.5 flex items-center gap-1.5">
                          {w.tags?.map((t) => (
                            <span key={t} className="rounded-full bg-accent/10 px-1.5 py-px text-2xs font-medium text-accent">
                              {t}
                            </span>
                          ))}
                          {w.ipinfo?.org && !w.tags?.length && (
                            <span className="truncate text-[11.5px] text-muted-foreground">{w.ipinfo.org}</span>
                          )}
                        </div>
                      </button>
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      <div className="flex flex-col gap-0.5">
                        <CountryChip iso={w.ipinfo?.country_iso} country={w.ipinfo?.country} />
                        {w.ipinfo?.ip && <Mono className="text-[11.5px] text-muted-foreground">{w.ipinfo.ip}</Mono>}
                      </div>
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      <StatusPill w={w} />
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      {w.proxy?.online ? (
                        <Mono className="text-muted-foreground">127.0.0.1:{w.proxy.port}</Mono>
                      ) : (
                        <span className="text-[12.5px] text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      <div className="flex items-center justify-end gap-0.5">
                        <Hint label={on ? "Disconnect" : "Connect"}>
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            disabled={isBusy}
                            className={on ? "text-ok hover:bg-bad-bg hover:text-bad" : ""}
                            onClick={() => act(w.name, on ? "stop" : "start", on ? "disconnecting…" : "connecting…")}
                          >
                            <Power />
                          </Button>
                        </Hint>
                        <Hint label="Live logs">
                          <Button size="icon-sm" variant="ghost" onClick={() => setLogsFor(w.name)}>
                            <ScrollText />
                          </Button>
                        </Hint>
                        <Hint label="Reconnect">
                          <Button size="icon-sm" variant="ghost" disabled={isBusy} onClick={() => act(w.name, "restart", "reconnecting…")}>
                            <RotateCw />
                          </Button>
                        </Hint>
                        <Hint label="Details">
                          <Button size="icon-sm" variant="ghost" onClick={() => setDetail(w.name)}>
                            <Info />
                          </Button>
                        </Hint>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* upload */}
      <Card>
        <CardBody>
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
            }}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-xl border border-dashed px-5 py-5 text-[13px] transition-colors",
              drag ? "border-accent bg-accent/5 text-foreground" : "border-border text-muted-foreground hover:border-accent/60 hover:text-foreground",
            )}
          >
            <Upload className="size-5 opacity-70" />
            <span>
              Drop <b>.ovpn</b> profiles here, or click to choose — each becomes a new exit in your fleet.
            </span>
            <input
              ref={fileRef}
              type="file"
              accept=".ovpn,.conf"
              multiple
              hidden
              onChange={(e) => {
                if (e.target.files?.length) upload(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        </CardBody>
      </Card>

      <ConnectionDrawer name={detail} onClose={() => setDetail(null)} onLogs={(n) => { setDetail(null); setLogsFor(n); }} />
      <LogsDrawer name={logsFor} onClose={() => setLogsFor(null)} />
    </div>
  );
}
