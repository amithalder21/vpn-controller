import { useEffect, useRef, useState } from "react";
import { sseUrl } from "@/lib/api";
import { Sheet } from "@/components/ui/sheet";

export function LogsDrawer({ name, onClose }: { name: string | null; onClose: () => void }) {
  const [lines, setLines] = useState<string[]>([]);
  const [state, setState] = useState("connecting…");
  const preRef = useRef<HTMLPreElement>(null);
  const autoscroll = useRef(true);

  useEffect(() => {
    if (!name) return;
    setLines([]);
    setState("connecting…");
    const src = new EventSource(sseUrl(`/api/workers/${name}/logs/stream?tail=200`));
    src.onopen = () => setState("streaming");
    src.onmessage = (e) => {
      setLines((prev) => {
        const next = [...prev, e.data];
        return next.length > 2000 ? next.slice(-2000) : next;
      });
    };
    src.onerror = () => setState("disconnected");
    return () => src.close();
  }, [name]);

  useEffect(() => {
    if (autoscroll.current && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <Sheet open={!!name} onOpenChange={(o) => !o && onClose()} title={`${name || ""} · logs`} meta={state} width="680px">
      <pre
        ref={preRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          autoscroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="flex-1 overflow-auto bg-[#0c0e12] px-4 py-3 font-mono text-[12px] leading-relaxed text-[#d4dae2]"
      >
        {lines.length ? lines.join("\n") : "waiting for output…"}
      </pre>
    </Sheet>
  );
}
