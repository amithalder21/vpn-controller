import { useEffect, useRef, useState } from "react";
import { Play, Square } from "lucide-react";
import { api, sseUrl } from "@/lib/api";
import { toast, useJobs, useScripts, useWorkers } from "@/lib/hooks";
import { Card, CardBody, CardHeader, CardSub, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common";
import { fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Pane {
  worker: string;
  lines: string;
  state: "running" | "done" | "err";
  code?: string;
}

export function Run() {
  const { data: workers = [] } = useWorkers();
  const { data: scripts = [] } = useScripts();
  const { data: jobs = [], refetch: refetchJobs } = useJobs();

  const [cmd, setCmd] = useState("curl -s https://ifconfig.co/country-iso");
  const [script, setScript] = useState("");
  const [timeout, setTimeoutS] = useState(60);
  const [panes, setPanes] = useState<Record<string, Pane>>({});
  const [jobState, setJobState] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const srcRef = useRef<EventSource | null>(null);

  useEffect(() => () => srcRef.current?.close(), []);

  async function run() {
    srcRef.current?.close();
    setPanes({});
    setJobState("starting…");
    const payload: any = script ? { script } : { body: cmd };
    payload.targets = "all";
    payload.timeout = timeout;
    try {
      const r = await api<{ job: string; targets: string[] }>("POST", "/api/run", payload);
      setJobId(r.job);
      const init: Record<string, Pane> = {};
      for (const t of r.targets) init[t] = { worker: t, lines: "", state: "running" };
      setPanes(init);
      setJobState(`0/${r.targets.length} done`);
      const src = new EventSource(sseUrl(`/api/jobs/${r.job}/stream`));
      srcRef.current = src;
      let done = 0;
      const total = r.targets.length;
      src.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        if (d.event === "done") {
          setJobState("finished");
          src.close();
          refetchJobs();
          return;
        }
        if (d.event === "start") return;
        if (d.event === "cancel") {
          toast(`Cancelled — killed ${d.total} process(es)`, "ok");
          return;
        }
        if (d.event === "exit") {
          done++;
          setJobState(`${done}/${total} done`);
          setPanes((p) => ({
            ...p,
            [d.worker]: {
              ...p[d.worker],
              worker: d.worker,
              lines: (p[d.worker]?.lines || "") + (d.line || ""),
              state: d.code === "0" ? "done" : "err",
              code: d.code,
            },
          }));
          return;
        }
        if (d.line !== undefined && d.worker) {
          setPanes((p) => ({
            ...p,
            [d.worker]: { ...(p[d.worker] || { worker: d.worker, state: "running" }), worker: d.worker, lines: (p[d.worker]?.lines || "") + d.line },
          }));
        }
      };
      src.onerror = () => setJobState("stream error");
    } catch (e: any) {
      toast(e.message, "err");
      setJobState("");
    }
  }

  async function cancel() {
    if (!jobId) return;
    try {
      const r = await api<{ killed: number }>("POST", `/api/jobs/${jobId}/cancel`, {});
      toast(`Cancelling — killed ${r.killed} process(es)`, "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
  }

  const online = workers.filter((w) => w.exists && w.vpn === "running").length;
  const paneList = Object.values(panes);
  const stateLabel = (p: Pane) =>
    p.state === "running" ? "running…" : p.code === "124" ? "timed out" : p.code === "143" ? "cancelled" : p.code === "0" ? "exit 0" : `exit ${p.code}`;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Run script / command</CardTitle>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground tabular">{online} online targets</span>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={script} onChange={(e) => setScript(e.target.value)} className="w-56">
              <option value="">Inline command ↓</option>
              {scripts.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
              Timeout
              <input
                type="number"
                min={1}
                max={3600}
                value={timeout}
                onChange={(e) => setTimeoutS(+e.target.value || 60)}
                className="h-9 w-20 rounded-md border border-input bg-background px-2 text-sm"
              />
              s
            </label>
            <div className="flex-1" />
            <Button variant="primary" onClick={run} disabled={!online}>
              <Play /> Run across fleet
            </Button>
          </div>
          {!script && (
            <Textarea
              value={cmd}
              onChange={(e) => setCmd(e.target.value)}
              spellCheck={false}
              placeholder="#!/bin/bash&#10;curl -s https://ifconfig.co/json"
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  run();
                }
              }}
            />
          )}
        </CardBody>
      </Card>

      {paneList.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Live output</CardTitle>
            <CardSub>{jobState}</CardSub>
            <div className="flex-1" />
            {jobState !== "finished" && (
              <Button size="sm" variant="danger" onClick={cancel}>
                <Square /> Cancel
              </Button>
            )}
          </CardHeader>
          <CardBody>
            <div className="grid gap-3 md:grid-cols-2">
              {paneList.map((p) => (
                <div key={p.worker} className="flex flex-col overflow-hidden rounded-xl border border-border bg-[#0c0e12]">
                  <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2 text-[12.5px]">
                    <span className="font-mono font-semibold text-white">{p.worker}</span>
                    <span className="flex-1" />
                    <span className={cn("text-[11.5px]", p.state === "done" ? "text-[#3fb973]" : p.state === "err" ? "text-[#ec6a5e]" : "text-[#8a93a1]")}>
                      {stateLabel(p)}
                    </span>
                  </div>
                  <pre className="max-h-64 min-h-[60px] overflow-auto px-3 py-2 font-mono text-[12px] leading-relaxed text-[#d4dae2]">
                    {p.lines || (p.state === "running" ? "waiting for output…" : "(no output)")}
                  </pre>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recent jobs</CardTitle>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">last 6h</span>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border/70 text-left text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-2.5 font-semibold">When</th>
                <th className="px-2 py-2.5 font-semibold">Script / command</th>
                <th className="px-2 py-2.5 font-semibold">Targets</th>
                <th className="px-2 py-2.5 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {!jobs.length && (
                <tr>
                  <td colSpan={4}>
                    <EmptyState>No jobs yet — run a script or command to see results here.</EmptyState>
                  </td>
                </tr>
              )}
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-border/60 last:border-0">
                  <td className="whitespace-nowrap px-4 py-2.5 text-[12.5px] text-muted-foreground tabular">{fmtRelative(j.ts)}</td>
                  <td className="px-2 py-2.5 font-mono text-[12.5px]">{j.label}</td>
                  <td className="px-2 py-2.5 text-[12.5px] text-muted-foreground tabular">{j.targets.length}</td>
                  <td className="px-2 py-2.5">
                    <Badge tone={j.status === "done" ? "ok" : j.status === "running" ? "warn" : "muted"} dot>
                      {j.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
