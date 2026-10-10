import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { keys, toast, useWorkers } from "@/lib/hooks";
import type { Worker } from "@/lib/types";
import { Sheet } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { SectionLabel, statusOf } from "@/components/common";
import { fmtBytes, fmtRate, fmtUptime } from "@/lib/format";
import { cn } from "@/lib/utils";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-[14px] font-medium tabular">{children}</div>
    </div>
  );
}

export function ConnectionDrawer({
  name,
  onClose,
  onLogs,
}: {
  name: string | null;
  onClose: () => void;
  onLogs: (n: string) => void;
}) {
  const qc = useQueryClient();
  const { data: workers = [] } = useWorkers(!!name);
  const w = workers.find((x) => x.name === name) as Worker | undefined;
  const [confirmDel, setConfirmDel] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: keys.workers });

  async function act(action: string, note?: string) {
    if (note && name) toast(`${name}: ${note}`, "info", 1400);
    try {
      await api("POST", `/api/workers/${name}/${action}`);
    } catch (e: any) {
      toast(`${name}: ${e.message}`, "err");
    }
    refresh();
  }

  async function del() {
    try {
      await api("DELETE", `/api/profiles/${name}`);
      toast(`${name} deleted`, "ok");
      onClose();
    } catch (e: any) {
      toast(`${name}: ${e.message}`, "err");
    }
    refresh();
  }

  async function rename() {
    const to = prompt("Rename connection to:", name || "");
    if (!to || to === name) return;
    try {
      await api("POST", `/api/profiles/${name}/rename`, { to });
      toast(`Renamed to ${to}`, "ok");
      onClose();
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }

  const on = !!w && w.exists && w.vpn === "running";
  const s = w ? statusOf(w) : null;
  const banner = { ok: "bg-ok-bg text-ok border-ok/25", warn: "bg-warn-bg text-warn border-warn/25", bad: "bg-bad-bg text-bad border-bad/25", muted: "bg-muted text-muted-foreground border-border" };

  return (
    <Sheet open={!!name} onOpenChange={(o) => !o && onClose()} title={name || ""} width="560px">
      {w && s && (
        <div className="flex-1 space-y-5 overflow-auto p-5">
          <div className={cn("flex items-center gap-2.5 rounded-xl border px-4 py-3 text-[14px] font-semibold", banner[s.tone])}>
            <span className="size-2 rounded-full bg-current" />
            {s.label}
          </div>

          <div className="grid grid-cols-2 gap-x-5 gap-y-4 rounded-xl border border-border/70 bg-muted/50 p-4">
            <Fact label="Exit IP">{w.ipinfo?.ip || "—"}</Fact>
            <Fact label="Location">{w.ipinfo?.country ? `${w.ipinfo.country_iso || ""} ${w.ipinfo.country}` : "—"}</Fact>
            <Fact label="Uptime">{on ? fmtUptime(w.started_at) : "—"}</Fact>
            <Fact label="Data used">
              {w.stats ? `${fmtBytes((w.stats.rx_mb || 0) * 1e6)} in · ${fmtBytes((w.stats.tx_mb || 0) * 1e6)} out` : "—"}
            </Fact>
            <Fact label="ISP / ASN">{w.ipinfo?.org || "—"}</Fact>
            <Fact label="Proxy">{w.proxy?.online ? `127.0.0.1:${w.proxy.port}` : "offline"}</Fact>
            <Fact label="Restarts">{w.restarts ?? 0}</Fact>
            <Fact label="Tags">{w.tags?.length ? w.tags.join(", ") : "none"}</Fact>
          </div>

          <div>
            <SectionLabel>Connection</SectionLabel>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant={on ? "secondary" : "primary"} onClick={() => act(on ? "stop" : "start", on ? "disconnecting…" : "connecting…")}>
                {on ? "Disconnect" : "Connect"}
              </Button>
              <Button size="sm" onClick={() => act("restart", "reconnecting…")}>Reconnect</Button>
              <Button size="sm" onClick={() => act("shutdown", "shutting down…")}>Shut down</Button>
              <Button size="sm" onClick={() => name && onLogs(name)}>Live logs</Button>
            </div>
          </div>

          <div>
            <SectionLabel>Exit checks</SectionLabel>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => act("ip", "checking exit IP…")}>Check exit IP</Button>
              <Button size="sm" onClick={() => act("leaktest", "running leak test…")}>Test exit (leak)</Button>
            </div>
            {w.leak && (
              <p className={cn("mt-2 text-[12.5px]", w.leak.pass ? "text-ok" : "text-bad")}>
                {w.leak.pass ? `Tunnelled — exit ${w.leak.exit_ip}` : `Leak risk: ${w.leak.reason}`}
              </p>
            )}
          </div>

          <div>
            <SectionLabel>Configuration</SectionLabel>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={rename}>Rename…</Button>
              {confirmDel ? (
                <Button size="sm" variant="primary" className="bg-bad hover:bg-bad/90" onClick={del}>
                  Click again to confirm delete
                </Button>
              ) : (
                <Button size="sm" variant="danger" onClick={() => { setConfirmDel(true); setTimeout(() => setConfirmDel(false), 4000); }}>
                  Delete connection
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </Sheet>
  );
}
