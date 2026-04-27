import { Plus } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { serverFetch } from "@/lib/api-server";
import type { TourSummary } from "@/lib/types";

import { QuickTourButton } from "./quick-tour";
import { SwipeableTourRow } from "./swipeable-tour-row";

export default async function ToursPage() {
  const tours = await serverFetch<TourSummary[]>("/tours");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold tracking-tight">Tours</h1>
        <div className="flex items-center gap-2">
          <QuickTourButton />
          <Link href="/tours/new" className={buttonVariants({ size: "sm" })}>
            <Plus className="size-4" strokeWidth={2.5} />
            <span className="ml-1">New tour</span>
          </Link>
        </div>
      </div>

      {tours.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 px-6 py-12 text-center">
          <h2 className="text-base font-semibold">No tours yet</h2>
          <p className="text-sm text-zinc-500 mt-1">
            Create a tour and add the houses you plan to visit.
          </p>
          <Link
            href="/tours/new"
            className={`${buttonVariants({ size: "lg" })} mt-4`}
          >
            Create your first tour
          </Link>
        </div>
      ) : (
        <>
          <p className="text-xs text-zinc-500 px-1">
            Swipe a tour left to delete.
          </p>
          <div className="grid gap-2">
            {tours.map((tour) => (
              <SwipeableTourRow key={tour.id} tour={tour} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
