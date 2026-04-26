"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { TourSummary } from "@/lib/types";

const SWIPE_REVEAL = 96; // px exposed when fully swiped
const SWIPE_THRESHOLD = 40; // commit to revealed state past this

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diffSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

export function SwipeableTourRow({ tour }: { tour: TourSummary }) {
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const startX = useRef<number | null>(null);
  const dragging = useRef(false);

  const del = useMutation({
    mutationFn: async () => {
      await clientFetch(`/tours/${tour.id}`, { method: "DELETE" });
    },
    onSuccess: () => {
      setConfirming(false);
      router.refresh();
    },
  });

  function onTouchStart(e: React.TouchEvent) {
    startX.current = e.touches[0].clientX;
    dragging.current = true;
  }

  function onTouchMove(e: React.TouchEvent) {
    if (!dragging.current || startX.current == null) return;
    const dx = e.touches[0].clientX - startX.current;
    // Only allow left swipe (negative dx). If currently revealed, allow right
    // swipe to close.
    const baseline = revealed ? -SWIPE_REVEAL : 0;
    const next = Math.min(0, Math.max(-SWIPE_REVEAL, baseline + dx));
    setOffset(next);
  }

  function onTouchEnd() {
    dragging.current = false;
    startX.current = null;
    if (offset < -SWIPE_THRESHOLD) {
      setOffset(-SWIPE_REVEAL);
      setRevealed(true);
    } else {
      setOffset(0);
      setRevealed(false);
    }
  }

  return (
    <div className="relative overflow-hidden rounded-xl">
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="absolute inset-y-0 right-0 flex items-center justify-center bg-red-600 text-white text-sm font-medium px-4 rounded-r-xl"
        style={{ width: SWIPE_REVEAL }}
        aria-label={`Delete ${tour.name}`}
      >
        Delete
      </button>

      <Link
        href={`/tours/${tour.id}`}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onClick={(e) => {
          if (revealed) {
            e.preventDefault();
            setOffset(0);
            setRevealed(false);
          }
        }}
        className="relative block rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4 hover:border-primary/50 hover:shadow-sm transition-all"
        style={{
          transform: `translateX(${offset}px)`,
          transition: dragging.current ? "none" : "transform 200ms",
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-semibold tracking-tight truncate">
              {tour.name}
            </div>
            {tour.location ? (
              <div className="text-sm text-zinc-600 dark:text-zinc-400 truncate">
                {tour.location}
              </div>
            ) : null}
          </div>
          {tour.in_progress_count > 0 ? (
            <span className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-1 rounded-md">
              <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
              live
            </span>
          ) : null}
        </div>

        <div className="mt-3 flex items-center gap-4 text-xs text-zinc-500">
          <span>
            <span className="font-medium text-zinc-700 dark:text-zinc-300">
              {tour.house_count}
            </span>{" "}
            {tour.house_count === 1 ? "house" : "houses"}
          </span>
          {tour.completed_count > 0 ? (
            <span>
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {tour.completed_count}
              </span>{" "}
              done
            </span>
          ) : null}
          {tour.avg_score != null ? (
            <span>
              avg{" "}
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {tour.avg_score.toFixed(1)}
              </span>
            </span>
          ) : null}
          {tour.last_activity_at ? (
            <span className="ml-auto">{timeAgo(tour.last_activity_at)}</span>
          ) : null}
        </div>
      </Link>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Delete this tour?"
      >
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Deletes <span className="font-medium">{tour.name}</span> along with
            every house, observation, transcript, and uploaded recording on it.
            Cannot be undone.
          </p>
          {del.isError ? (
            <p className="text-sm text-red-600 dark:text-red-400">
              {del.error instanceof Error
                ? del.error.message
                : "Delete failed"}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => del.mutate()}
              disabled={del.isPending}
            >
              {del.isPending ? "Deleting…" : "Delete tour"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
