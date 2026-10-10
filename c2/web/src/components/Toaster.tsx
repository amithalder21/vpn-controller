import { CheckCircle2, Info, XCircle } from "lucide-react";
import { dismissToast, useToasts } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const icon = { ok: CheckCircle2, err: XCircle, info: Info };
const accent = {
  ok: "border-l-ok",
  err: "border-l-bad",
  info: "border-l-accent",
};
const iconColor = { ok: "text-ok", err: "text-bad", info: "text-accent" };

export function Toaster() {
  const toasts = useToasts();
  return (
    <div className="fixed bottom-5 right-5 z-[90] flex max-w-[min(92vw,420px)] flex-col gap-2">
      {toasts.map((t) => {
        const Icon = icon[t.kind];
        return (
          <button
            key={t.id}
            onClick={() => dismissToast(t.id)}
            className={cn(
              "flex items-start gap-2.5 rounded-xl border border-l-[3px] border-border bg-card px-3.5 py-2.5 text-left text-[13px] shadow-pop animate-pop-in",
              accent[t.kind],
            )}
          >
            <Icon className={cn("mt-px size-4 shrink-0", iconColor[t.kind])} />
            <span className="whitespace-pre-wrap">{t.text}</span>
          </button>
        );
      })}
    </div>
  );
}
