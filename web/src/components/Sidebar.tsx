import { Activity, Clock3, LayoutGrid, Radar, Server, Settings, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";

export type ViewId = "overview" | "connections" | "run" | "probe" | "schedules" | "activity" | "settings";

const NAV: { id: ViewId; label: string; icon: typeof Activity }[] = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "connections", label: "Connections", icon: Server },
  { id: "run", label: "Run script", icon: Terminal },
  { id: "probe", label: "Probe", icon: Radar },
  { id: "schedules", label: "Schedules", icon: Clock3 },
  { id: "activity", label: "Activity", icon: Activity },
  { id: "settings", label: "Settings", icon: Settings },
];

function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="size-[17px]">
      <circle cx="12" cy="12" r="2.6" />
      <circle cx="6" cy="6" r="1.8" />
      <circle cx="18" cy="6" r="1.8" />
      <circle cx="12" cy="19.5" r="1.8" />
      <path d="M10.2 10.2 7.3 7.3M13.8 10.2l2.9-2.9M12 14.6v3.1" />
    </svg>
  );
}

export function Sidebar({
  view,
  setView,
  issues,
  connState,
}: {
  view: ViewId;
  setView: (v: ViewId) => void;
  issues: number;
  connState: { kind: "live" | "err" | "wait"; text: string };
}) {
  const dotColor = { live: "bg-ok", err: "bg-bad", wait: "bg-warn" }[connState.kind];
  return (
    <aside className="sticky top-0 flex h-screen w-[244px] shrink-0 flex-col bg-rail text-rail-foreground">
      <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
        <span className="grid size-8 place-items-center rounded-[10px] bg-white/10 text-white ring-1 ring-white/10">
          <BrandMark />
        </span>
        <div className="leading-tight">
          <div className="text-[15px] font-bold tracking-tight">Flotilla</div>
          <div className="text-2xs font-medium text-rail-muted">Fleet control plane</div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-3 py-2">
        {NAV.map(({ id, label, icon: Icon }) => {
          const active = view === id;
          return (
            <button
              key={id}
              onClick={() => setView(id)}
              className={cn(
                "group relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors",
                active ? "bg-white/10 text-white" : "text-rail-muted hover:bg-rail-hover hover:text-rail-foreground",
              )}
            >
              {active && <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-rail-active" />}
              <Icon className={cn("size-[17px] shrink-0", active ? "text-rail-active" : "")} strokeWidth={2} />
              <span>{label}</span>
              {id === "connections" && issues > 0 && (
                <span className="ml-auto grid h-[18px] min-w-[18px] place-items-center rounded-full bg-bad px-1.5 text-[11px] font-bold text-white">
                  {issues}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-white/10 px-4 py-3.5">
        <span className="inline-flex items-center gap-2 text-xs text-rail-muted">
          <span className={cn("size-2 rounded-full", dotColor)} />
          {connState.text}
        </span>
      </div>
    </aside>
  );
}
