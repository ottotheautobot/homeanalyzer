"use client";

import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  LayoutGrid,
  MessageCircle,
  Quote,
  Video,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { createSupabaseBrowserClient } from "@/lib/supabase/browser";
import type { Observation } from "@/lib/types";

const CATEGORY_META: Record<
  Observation["category"],
  { label: string; Icon: LucideIcon; ring: string; chip: string }
> = {
  hazard: {
    label: "Hazard",
    Icon: AlertTriangle,
    ring: "border-red-200 dark:border-red-900/60",
    chip: "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300",
  },
  concern: {
    label: "Concern",
    Icon: CircleAlert,
    ring: "border-amber-200 dark:border-amber-900/60",
    chip: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300",
  },
  positive: {
    label: "Positive",
    Icon: CheckCircle2,
    ring: "border-emerald-200 dark:border-emerald-900/60",
    chip: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300",
  },
  layout: {
    label: "Layout",
    Icon: LayoutGrid,
    ring: "border-zinc-200 dark:border-zinc-800",
    chip: "bg-zinc-100 dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300",
  },
  condition: {
    label: "Condition",
    Icon: Wrench,
    ring: "border-zinc-200 dark:border-zinc-800",
    chip: "bg-zinc-100 dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300",
  },
  agent_said: {
    label: "Agent",
    Icon: Quote,
    ring: "border-blue-200 dark:border-blue-900/60",
    chip: "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300",
  },
  partner_said: {
    label: "Partner",
    Icon: MessageCircle,
    ring: "border-violet-200 dark:border-violet-900/60",
    chip: "bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300",
  },
};

const SEVERITY_TONE: Record<NonNullable<Observation["severity"]>, string> = {
  info: "text-zinc-500",
  warn: "text-amber-600 dark:text-amber-400",
  critical: "text-red-600 dark:text-red-400 font-semibold",
};

function formatTimestamp(seconds: number | null) {
  if (seconds == null) return null;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function ObservationFeed({
  houseId,
  initial,
}: {
  houseId: string;
  initial: Observation[];
}) {
  const [observations, setObservations] = useState<Observation[]>(initial);

  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    const channel = supabase
      .channel(`obs:${houseId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "observations",
          filter: `house_id=eq.${houseId}`,
        },
        (payload) => {
          const next = payload.new as Observation;
          setObservations((prev) =>
            prev.some((o) => o.id === next.id) ? prev : [...prev, next],
          );
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [houseId]);

  if (observations.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 px-6 py-10 text-center">
        <p className="text-sm text-zinc-500">
          No observations yet. They&apos;ll appear here as the bot hears the tour.
        </p>
      </div>
    );
  }

  return (
    <ul className="space-y-2">
      {observations.map((obs) => {
        const meta = CATEGORY_META[obs.category];
        const Icon = meta.Icon;
        return (
          <li
            key={obs.id}
            className={`flex gap-3 rounded-xl border ${meta.ring} bg-white dark:bg-zinc-950 p-3`}
          >
            <span
              className={`shrink-0 inline-flex items-center justify-center size-8 rounded-lg ${meta.chip}`}
              aria-hidden="true"
            >
              <Icon className="size-4" strokeWidth={2.25} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2 text-[11px] mb-0.5">
                <div className="flex items-center gap-1.5 min-w-0 text-zinc-500">
                  <span className="font-medium uppercase tracking-wide">
                    {meta.label}
                  </span>
                  {obs.source === "photo_analysis" ? (
                    <span
                      className="inline-flex items-center gap-0.5 text-primary"
                      title="From video analysis"
                    >
                      <Video className="size-3" strokeWidth={2.25} />
                    </span>
                  ) : null}
                  {obs.room ? (
                    <span className="truncate">· {obs.room}</span>
                  ) : null}
                  {obs.severity ? (
                    <span
                      className={`uppercase tracking-wide ${SEVERITY_TONE[obs.severity]}`}
                    >
                      · {obs.severity}
                    </span>
                  ) : null}
                </div>
                <span className="text-zinc-400 tabular-nums shrink-0">
                  {formatTimestamp(obs.recall_timestamp) ??
                    formatDistanceToNow(new Date(obs.created_at), {
                      addSuffix: true,
                    })}
                </span>
              </div>
              <div className="text-sm text-zinc-900 dark:text-zinc-100 leading-snug">
                {obs.content}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
