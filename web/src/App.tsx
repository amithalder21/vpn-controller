import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getToken, setToken } from "@/lib/api";
import { useWorkers } from "@/lib/hooks";
import { Sidebar, type ViewId } from "@/components/Sidebar";
import { Toaster } from "@/components/Toaster";
import { TokenGate } from "@/components/TokenGate";
import { Overview } from "@/views/Overview";
import { Connections } from "@/views/Connections";
import { Run } from "@/views/Run";
import { Probe } from "@/views/Probe";
import { Schedules } from "@/views/Schedules";
import { Activity } from "@/views/Activity";
import { Settings } from "@/views/Settings";

const META: Record<ViewId, { title: string; sub: string }> = {
  overview: { title: "Overview", sub: "Fleet at a glance" },
  connections: { title: "Connections", sub: "Your exits, live" },
  run: { title: "Run script", sub: "Execute across every exit" },
  probe: { title: "Probe", sub: "Compare a request from every exit" },
  schedules: { title: "Schedules", sub: "Recurring jobs" },
  activity: { title: "Activity", sub: "What the fleet has been doing" },
  settings: { title: "Settings", sub: "Token, auto-heal, proxy pool" },
};

function Shell({ onDeauth }: { onDeauth: () => void }) {
  const qc = useQueryClient();
  const [view, setView] = useState<ViewId>("overview");
  const { data: workers = [], isError, error, isLoading } = useWorkers();

  useEffect(() => {
    if (isError && (error as any)?.status === 401) {
      setToken("");
      onDeauth();
    }
  }, [isError, error, onDeauth]);

  const issues = workers.filter((w) => w.gaveup || (w.vpn === "running" && w.health === "unhealthy")).length;
  const connState = isError
    ? { kind: "err" as const, text: "disconnected" }
    : isLoading
      ? { kind: "wait" as const, text: "connecting…" }
      : { kind: "live" as const, text: "connected" };

  const m = META[view];

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar view={view} setView={setView} issues={issues} connState={connState} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-[60px] items-center gap-3 border-b border-border bg-background/80 px-7 backdrop-blur-md">
          <div>
            <h1 className="text-[16px] font-bold tracking-tight">{m.title}</h1>
          </div>
          <span className="hidden text-[12.5px] text-muted-foreground sm:inline">· {m.sub}</span>
        </header>
        <main className="mx-auto w-full max-w-[1360px] flex-1 px-7 py-6">
          {view === "overview" && <Overview setView={setView} />}
          {view === "connections" && <Connections />}
          {view === "run" && <Run />}
          {view === "probe" && <Probe />}
          {view === "schedules" && <Schedules />}
          {view === "activity" && <Activity />}
          {view === "settings" && <Settings />}
        </main>
      </div>
      <Toaster />
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const qc = useQueryClient();

  if (!authed) {
    return (
      <>
        <TokenGate
          onAuthed={() => {
            qc.invalidateQueries();
            setAuthed(true);
          }}
        />
        <Toaster />
      </>
    );
  }
  return <Shell onDeauth={() => setAuthed(false)} />;
}
