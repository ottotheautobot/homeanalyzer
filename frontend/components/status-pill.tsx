import { cn } from "@/lib/utils";
import type { House } from "@/lib/types";

const STATUS: Record<
  House["status"],
  { label: string; cls: string; live?: boolean }
> = {
  upcoming: {
    label: "Not toured",
    cls: "bg-zinc-100 dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400",
  },
  touring: {
    label: "Live",
    cls: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400",
    live: true,
  },
  synthesizing: {
    label: "Generating brief…",
    cls: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
  },
  completed: {
    label: "Brief ready",
    cls: "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400",
  },
};

export function StatusPill({
  status,
  className,
}: {
  status: House["status"];
  className?: string;
}) {
  const s = STATUS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-md",
        s.cls,
        className,
      )}
    >
      {s.live ? (
        <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
      ) : null}
      {s.label}
    </span>
  );
}
