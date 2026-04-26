"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { Tour } from "@/lib/types";

const SWIPE_REVEAL = 96; // px exposed when fully swiped
const SWIPE_THRESHOLD = 40; // commit to revealed state past this

export function SwipeableTourRow({ tour }: { tour: Tour }) {
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
    <div className="relative overflow-hidden rounded-lg">
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="absolute inset-y-0 right-0 flex items-center justify-center bg-red-600 text-white text-sm font-medium px-4"
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
        className="relative block rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
        style={{
          transform: `translateX(${offset}px)`,
          transition: dragging.current ? "none" : "transform 200ms",
        }}
      >
        <div className="flex items-baseline justify-between gap-3">
          <div>
            <div className="font-medium">{tour.name}</div>
            {tour.location ? (
              <div className="text-sm text-zinc-600 dark:text-zinc-400">
                {tour.location}
              </div>
            ) : null}
          </div>
          <span className="text-xs uppercase tracking-wide text-zinc-500">
            {tour.status}
          </span>
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
