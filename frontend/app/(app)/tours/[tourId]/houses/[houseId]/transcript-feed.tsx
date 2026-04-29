"use client";

import { useEffect, useState } from "react";

import { createSupabaseBrowserClient } from "@/lib/supabase/browser";
import type { Transcript } from "@/lib/types";

function formatTimestamp(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TranscriptFeed({
  houseId,
  initial,
}: {
  houseId: string;
  initial: Transcript[];
}) {
  const [lines, setLines] = useState<Transcript[]>(initial);

  useEffect(() => {
    const supabase = createSupabaseBrowserClient();
    const channel = supabase
      .channel(`transcripts:${houseId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "transcripts",
          filter: `house_id=eq.${houseId}`,
        },
        (payload) => {
          const t = payload.new as Transcript;
          setLines((prev) =>
            prev.some((p) => p.id === t.id) ? prev : [...prev.slice(-200), t],
          );
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [houseId]);

  if (lines.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        Waiting for someone to speak — transcript lines will appear here as
        the tour talks through the home.
      </p>
    );
  }

  return (
    <ul className="space-y-1.5 text-sm">
      {lines.map((t) => (
        <li
          key={t.id}
          className="flex gap-3 leading-snug animate-in fade-in slide-in-from-bottom-1 duration-300"
        >
          <span className="shrink-0 text-xs text-zinc-400 tabular-nums w-10 mt-0.5">
            {formatTimestamp(t.start_seconds)}
          </span>
          <div className="flex-1 min-w-0">
            {t.speaker ? (
              <span className="text-xs uppercase tracking-wide text-primary mr-1.5">
                {t.speaker}
              </span>
            ) : null}
            <span className="text-zinc-700 dark:text-zinc-300">{t.text}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}
