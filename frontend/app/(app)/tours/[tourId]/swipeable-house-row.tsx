"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { House } from "@/lib/types";

const SWIPE_REVEAL = 96;
const SWIPE_THRESHOLD = 40;

const STATUS_TONE: Record<House["status"], string> = {
  upcoming: "text-zinc-500",
  touring: "text-amber-600 dark:text-amber-400",
  synthesizing: "text-amber-600 dark:text-amber-400",
  completed: "text-emerald-600 dark:text-emerald-400",
};

function formatPrice(n: number | null) {
  if (n == null) return null;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function SwipeableHouseRow({
  tourId,
  house,
}: {
  tourId: string;
  house: House;
}) {
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const startX = useRef<number | null>(null);
  const dragging = useRef(false);

  const del = useMutation({
    mutationFn: async () => {
      await clientFetch(`/houses/${house.id}`, { method: "DELETE" });
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

  const price = formatPrice(house.list_price);

  return (
    <div className="relative overflow-hidden rounded-xl">
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="absolute inset-y-0 right-0 flex items-center justify-center bg-red-600 text-white text-sm font-medium px-4 rounded-r-xl"
        style={{ width: SWIPE_REVEAL }}
        aria-label={`Delete ${house.address}`}
      >
        Delete
      </button>

      <Link
        href={`/tours/${tourId}/houses/${house.id}`}
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
        <div className="flex items-center gap-3">
          {house.photo_signed_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={house.photo_signed_url}
              alt=""
              className="size-14 rounded-lg object-cover shrink-0 border border-zinc-200 dark:border-zinc-800"
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <div className="font-medium truncate">{house.address}</div>
            <div className="text-sm text-zinc-600 dark:text-zinc-400 truncate">
              {[
                price,
                house.beds != null ? `${house.beds} bd` : null,
                house.baths != null ? `${house.baths} ba` : null,
                house.sqft != null
                  ? `${house.sqft.toLocaleString()} sqft`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
          <span
            className={`text-xs uppercase tracking-wide shrink-0 ${STATUS_TONE[house.status]}`}
          >
            {house.status}
            {house.overall_score != null
              ? ` · ${house.overall_score.toFixed(1)}`
              : ""}
          </span>
        </div>
      </Link>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Delete this house?"
      >
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Deletes <span className="font-medium">{house.address}</span> along
            with every observation, transcript, and uploaded recording. The
            bot will be stopped if it&apos;s still active. Cannot be undone.
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
              {del.isPending ? "Deleting…" : "Delete house"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
