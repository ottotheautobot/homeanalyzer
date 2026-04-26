"use client";

import { useEffect, useState } from "react";

import { createSupabaseBrowserClient } from "@/lib/supabase/browser";
import type { Transcript } from "@/lib/types";

function formatTimestamp(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TranscriptFeed({ houseId }: { houseId: string }) {
  const [lines, setLines] = useState<Transcript[]>([]);

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
            prev.some((p) => p.id === t.id) ? prev : [...prev.slice(-50), t],
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
        Waiting for the bot to start hearing audio…
      </p>
    );
  }

  return (
    <ul className="space-y-1 text-sm">
      {lines.map((t) => (
        <li
          key={t.id}
          className="flex gap-2 text-zinc-700 dark:text-zinc-300 leading-snug"
        >
          <span className="shrink-0 text-xs text-zinc-400 tabular-nums w-10 mt-1">
            {formatTimestamp(t.start_seconds)}
          </span>
          {t.speaker ? (
            <span className="shrink-0 text-xs uppercase tracking-wide text-zinc-500 mt-1">
              {t.speaker}
            </span>
          ) : null}
          <span className="flex-1">{t.text}</span>
        </li>
      ))}
    </ul>
  );
}
