"use client";

import { formatDistanceToNow } from "date-fns";
import { useEffect, useState } from "react";

import { createSupabaseBrowserClient } from "@/lib/supabase/browser";
import type { Observation } from "@/lib/types";

const CATEGORY_LABEL: Record<Observation["category"], string> = {
  layout: "Layout",
  condition: "Condition",
  hazard: "Hazard",
  positive: "Positive",
  concern: "Concern",
  agent_said: "Agent said",
  partner_said: "Partner said",
};

const SEVERITY_TONE: Record<NonNullable<Observation["severity"]>, string> = {
  info: "text-zinc-500",
  warn: "text-amber-600 dark:text-amber-400",
  critical: "text-red-600 dark:text-red-400",
};

const CATEGORY_TONE: Record<Observation["category"], string> = {
  hazard: "border-red-300 dark:border-red-900",
  concern: "border-amber-300 dark:border-amber-900",
  positive: "border-emerald-300 dark:border-emerald-900",
  layout: "border-zinc-200 dark:border-zinc-800",
  condition: "border-zinc-200 dark:border-zinc-800",
  agent_said: "border-blue-300 dark:border-blue-900",
  partner_said: "border-violet-300 dark:border-violet-900",
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
      <p className="text-sm text-zinc-500">
        No observations yet. Upload audio to begin transcription.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {observations.map((obs) => (
        <li
          key={obs.id}
          className={`rounded-lg border-l-4 ${CATEGORY_TONE[obs.category]} bg-white dark:bg-zinc-950 px-4 py-3`}
        >
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400">
              {CATEGORY_LABEL[obs.category]}
              {obs.room ? ` · ${obs.room}` : ""}
              {obs.severity ? (
                <>
                  {" · "}
                  <span className={SEVERITY_TONE[obs.severity]}>
                    {obs.severity}
                  </span>
                </>
              ) : null}
            </span>
            <span className="text-zinc-400">
              {formatTimestamp(obs.recall_timestamp) ??
                formatDistanceToNow(new Date(obs.created_at), {
                  addSuffix: true,
                })}
            </span>
          </div>
          <div className="mt-1 text-sm text-zinc-900 dark:text-zinc-100">
            {obs.content}
          </div>
        </li>
      ))}
    </ul>
  );
}
