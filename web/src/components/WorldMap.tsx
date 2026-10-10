import { useEffect, useMemo, useState } from "react";
import type { Worker } from "@/lib/types";
import { EmptyState } from "./common";

interface MapData {
  w: number;
  h: number;
  land: string;
  cents: Record<string, [number, number]>;
}

let cache: MapData | null = null;

export function WorldMap({ workers }: { workers: Worker[] }) {
  const [map, setMap] = useState<MapData | null>(cache);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (cache) return;
    fetch(`${import.meta.env.BASE_URL}mapdata.json`, { cache: "force-cache" })
      .then((r) => r.json())
      .then((d: MapData) => {
        cache = d;
        setMap(d);
      })
      .catch(() => setFailed(true));
  }, []);

  const groups = useMemo(() => {
    const g: Record<string, { iso: string; country: string; count: number; online: number }> = {};
    for (const w of workers) {
      const iso = w.ipinfo?.country_iso?.toLowerCase();
      if (!iso) continue;
      if (!g[iso]) g[iso] = { iso, country: w.ipinfo?.country || iso.toUpperCase(), count: 0, online: 0 };
      g[iso].count++;
      if (w.exists && w.vpn === "running" && w.health === "healthy") g[iso].online++;
    }
    return g;
  }, [workers]);

  if (failed) return <EmptyState>Map unavailable.</EmptyState>;
  if (!map) return <EmptyState>Loading map…</EmptyState>;

  const located = Object.values(groups).filter((g) => map.cents[g.iso]);

  return (
    <div className="relative w-full">
      <svg
        viewBox={`0 42 ${map.w} 356`}
        preserveAspectRatio="xMidYMid meet"
        className="mx-auto block h-auto max-h-[300px] w-full"
        role="img"
        aria-label="World map of exit locations"
      >
        <path d={map.land} className="fill-muted stroke-border" strokeWidth={0.5} />
        {located.map((g) => {
          const [x, y] = map.cents[g.iso];
          const live = g.online > 0;
          const color = live ? "hsl(var(--accent))" : "hsl(var(--muted-foreground))";
          const r = Math.min(5 + g.count * 2.2, 13);
          return (
            <g key={g.iso}>
              {live && <circle cx={x} cy={y} r={r + 5} fill={color} opacity={0.14} />}
              <circle cx={x} cy={y} r={r} fill={color} opacity={0.92} />
              {g.count > 1 && (
                <text x={x} y={y} textAnchor="middle" dominantBaseline="central"
                  style={{ fontSize: 11, fontWeight: 700, paintOrder: "stroke" }} className="fill-white">
                  {g.count}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="mt-3 flex flex-wrap items-center gap-4 border-t border-border/70 pt-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-[9px] rounded-full" style={{ background: "hsl(var(--accent))" }} /> Online exit
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-[9px] rounded-full" style={{ background: "hsl(var(--muted-foreground))" }} /> Offline
        </span>
        <span className="ml-auto tabular">
          {located.length ? `${located.length} ${located.length === 1 ? "country" : "countries"}` : "No located exits yet — connect a tunnel to see it here."}
        </span>
      </div>
    </div>
  );
}
