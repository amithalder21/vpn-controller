import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/common";
import { useEvents } from "@/lib/hooks";
import { fmtTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  connect: "bg-ok-bg text-ok",
  reconnect: "bg-ok-bg text-ok",
  renamed: "bg-ok-bg text-ok",
  disconnect: "bg-muted text-muted-foreground",
  shutdown: "bg-muted text-muted-foreground",
  autoheal: "bg-warn-bg text-warn",
  gaveup: "bg-bad-bg text-bad",
  "heal-error": "bg-bad-bg text-bad",
};

export function Activity() {
  const { data: events = [] } = useEvents();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Activity</CardTitle>
        <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">most recent</span>
      </CardHeader>
      <CardBody className="max-h-[70vh] overflow-auto">
        {!events.length ? (
          <EmptyState>No activity yet — connects, actions and auto-heals will show up here.</EmptyState>
        ) : (
          <div className="flex flex-col">
            {events.map((e) => (
              <div key={e.id} className="flex items-baseline gap-3 border-b border-border/50 py-2.5 text-[12.5px] last:border-0">
                <span className="w-20 shrink-0 text-[11.5px] text-muted-foreground tabular">{fmtTime(Number(e.ts))}</span>
                <span className="w-32 shrink-0">
                  <span className={cn("inline-block rounded-full px-2.5 py-0.5 text-[11px] font-medium", TONE[e.kind] || "bg-muted text-muted-foreground")}>
                    {e.kind}
                  </span>
                </span>
                <span className="w-40 shrink-0 font-mono font-medium">{e.name !== "-" ? e.name : ""}</span>
                <span className="text-muted-foreground">{e.detail}</span>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
