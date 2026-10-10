import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium tabular",
  {
    variants: {
      tone: {
        ok: "bg-ok-bg text-ok",
        warn: "bg-warn-bg text-warn",
        bad: "bg-bad-bg text-bad",
        muted: "bg-muted text-muted-foreground",
        accent: "bg-accent/10 text-accent",
      },
    },
    defaultVariants: { tone: "muted" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

export function Badge({ className, tone, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot && <span className="size-[7px] rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}
