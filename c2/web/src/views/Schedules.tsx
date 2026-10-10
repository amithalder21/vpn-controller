import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Play, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { keys, toast, useScripts, useSchedules } from "@/lib/hooks";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common";
import { fmtRelative, fmtTime } from "@/lib/format";

export function Schedules() {
  const qc = useQueryClient();
  const { data: schedules = [] } = useSchedules();
  const { data: scripts = [] } = useScripts();
  const refresh = () => qc.invalidateQueries({ queryKey: keys.schedules });

  const [name, setName] = useState("");
  const [cron, setCron] = useState("0 3 * * *");
  const [script, setScript] = useState("");
  const [body, setBody] = useState("");
  const [timeout, setTimeoutS] = useState(300);

  async function create() {
    if (!name.trim()) return toast("Name the schedule first", "err");
    const payload: any = { name, cron, targets: "all", timeout };
    if (script) payload.script = script;
    else payload.body = body;
    try {
      await api("POST", "/api/schedules", payload);
      toast("Schedule created", "ok");
      setName("");
      setBody("");
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }

  async function toggle(id: string, enabled: boolean) {
    try {
      await api("POST", `/api/schedules/${id}`, { enabled });
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }
  async function runNow(id: string) {
    try {
      await api("POST", `/api/schedules/${id}/run`, {});
      toast("Schedule triggered", "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }
  async function del(id: string) {
    try {
      await api("DELETE", `/api/schedules/${id}`);
      toast("Schedule deleted", "ok");
    } catch (e: any) {
      toast(e.message, "err");
    }
    refresh();
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>New schedule</CardTitle>
        </CardHeader>
        <CardBody>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="flex flex-col gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
              Name
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nightly leak test" className="font-normal text-foreground" />
            </label>
            <label className="flex flex-col gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
              Cron (m h dom mon dow)
              <Input value={cron} onChange={(e) => setCron(e.target.value)} className="font-mono text-[13px] text-foreground" />
            </label>
            <label className="flex flex-col gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
              Timeout (s)
              <Input type="number" value={timeout} onChange={(e) => setTimeoutS(+e.target.value || 300)} className="font-normal text-foreground" />
            </label>
            <label className="flex flex-col gap-1.5 text-[11.5px] font-semibold text-muted-foreground md:col-span-1">
              Script
              <Select value={script} onChange={(e) => setScript(e.target.value)} className="font-normal text-foreground">
                <option value="">Inline command →</option>
                {scripts.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </Select>
            </label>
            {!script && (
              <label className="flex flex-col gap-1.5 text-[11.5px] font-semibold text-muted-foreground md:col-span-2">
                Inline command
                <Input value={body} onChange={(e) => setBody(e.target.value)} placeholder="curl -s https://ifconfig.co/json" className="font-mono text-[13px] text-foreground" />
              </label>
            )}
          </div>
          <div className="mt-3">
            <Button variant="primary" onClick={create}>
              Create schedule
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scheduled jobs</CardTitle>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground tabular">{schedules.length}</span>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border/70 text-left text-2xs uppercase tracking-wider text-muted-foreground">
                <th className="px-4 py-2.5 font-semibold">Name</th>
                <th className="px-2 py-2.5 font-semibold">Cron</th>
                <th className="px-2 py-2.5 font-semibold">Last run</th>
                <th className="px-2 py-2.5 font-semibold">Next run</th>
                <th className="px-2 py-2.5 font-semibold">On</th>
                <th className="px-2 py-2.5 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {!schedules.length && (
                <tr>
                  <td colSpan={6}>
                    <EmptyState>No schedules yet — create one above.</EmptyState>
                  </td>
                </tr>
              )}
              {schedules.map((s) => (
                <tr key={s.id} className="border-b border-border/60 last:border-0">
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{s.name}</div>
                    <div className="font-mono text-[11.5px] text-muted-foreground">{s.script || s.body}</div>
                  </td>
                  <td className="px-2 py-2.5 font-mono text-[12.5px] text-muted-foreground">{s.cron}</td>
                  <td className="px-2 py-2.5 text-[12.5px]">
                    {s.last_run ? (
                      <span className="text-muted-foreground tabular">{fmtRelative(s.last_run)}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                    {s.last_status && <div className="text-[11px] text-muted-foreground">{s.last_status}</div>}
                  </td>
                  <td className="px-2 py-2.5 text-[12.5px] text-muted-foreground tabular">{s.next_run ? fmtTime(s.next_run) : "—"}</td>
                  <td className="px-2 py-2.5">
                    <Switch checked={s.enabled} onCheckedChange={(v) => toggle(s.id, v)} />
                  </td>
                  <td className="px-2 py-2.5">
                    <div className="flex items-center justify-end gap-1">
                      <Button size="icon-sm" variant="ghost" title="Run now" onClick={() => runNow(s.id)}>
                        <Play />
                      </Button>
                      <Button size="icon-sm" variant="ghost" className="hover:text-bad" title="Delete" onClick={() => del(s.id)}>
                        <Trash2 />
                      </Button>
                    </div>
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
