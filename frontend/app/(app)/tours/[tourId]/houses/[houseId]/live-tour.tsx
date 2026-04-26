"use client";

import { useMutation } from "@tanstack/react-query";
import { Square, Video } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { House } from "@/lib/types";

function formatElapsed(startedAt: string | null): string {
  if (!startedAt) return "0:00";
  const start = new Date(startedAt).getTime();
  const sec = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function LiveTour({
  house,
  zoomUrl,
  startedAt,
}: {
  house: House;
  zoomUrl: string | null;
  startedAt: string | null;
}) {
  const router = useRouter();
  const [elapsed, setElapsed] = useState(() => formatElapsed(startedAt));

  useEffect(() => {
    const id = setInterval(() => setElapsed(formatElapsed(startedAt)), 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const endTour = useMutation({
    mutationFn: async (): Promise<House> =>
      clientFetch<House>(`/houses/${house.id}/end_tour`, { method: "POST" }),
    onSuccess: () => router.refresh(),
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="relative inline-flex items-center justify-center size-2.5">
            <span className="absolute inset-0 rounded-full bg-emerald-500 animate-ping opacity-60" />
            <span className="relative inline-block size-2 rounded-full bg-emerald-500" />
          </span>
          <span className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
            Bot in meeting
          </span>
        </div>
        <span className="font-mono text-sm tabular-nums text-zinc-500">
          {elapsed}
        </span>
      </div>

      {zoomUrl ? (
        <a
          href={zoomUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 px-3 py-2.5 hover:border-primary/40 hover:bg-zinc-100 dark:hover:bg-zinc-900 transition-colors"
        >
          <span className="inline-flex items-center justify-center size-8 rounded-md bg-primary/10 text-primary">
            <Video className="size-4" strokeWidth={2.25} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium leading-tight">
              Open Zoom meeting
            </div>
            <div className="text-xs text-zinc-500 truncate">{zoomUrl}</div>
          </div>
          <span className="text-zinc-400 shrink-0 text-sm">→</span>
        </a>
      ) : null}

      <Button
        variant="destructive"
        onClick={() => endTour.mutate()}
        disabled={endTour.isPending}
        size="lg"
        className="w-full"
      >
        <Square className="size-4 mr-1.5" fill="currentColor" />
        {endTour.isPending ? "Ending tour…" : "End tour"}
      </Button>
      {endTour.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {endTour.error instanceof Error
            ? endTour.error.message
            : "Failed to end tour"}
        </p>
      ) : null}
    </div>
  );
}
