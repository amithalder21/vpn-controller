import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function Sheet({
  open,
  onOpenChange,
  title,
  meta,
  width = "620px",
  children,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: React.ReactNode;
  meta?: React.ReactNode;
  width?: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[70] bg-primary/35 backdrop-blur-[1px] data-[state=open]:animate-fade-in" />
        <Dialog.Content
          className={cn(
            "fixed right-0 top-0 z-[71] flex h-screen flex-col border-l border-border bg-card shadow-[-12px_0_40px_rgba(16,24,40,.18)]",
            "data-[state=open]:animate-slide-in-right focus:outline-none",
          )}
          style={{ width: `min(${width}, 94vw)` }}
        >
          <div className="flex flex-wrap items-center gap-2 border-b border-border/70 px-4 py-3">
            <Dialog.Title className="font-mono text-sm font-semibold">{title}</Dialog.Title>
            {meta && <span className="text-xs text-muted-foreground tabular">{meta}</span>}
            <div className="flex-1" />
            <Dialog.Close className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
              <X className="size-4" /> Close
            </Dialog.Close>
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
