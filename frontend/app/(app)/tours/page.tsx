import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { Tour } from "@/lib/types";

import { SwipeableTourRow } from "./swipeable-tour-row";

export default async function ToursPage() {
  const tours = await serverFetch<Tour[]>("/tours");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Tours</h1>
        <Link href="/tours/new" className={buttonVariants()}>
          New tour
        </Link>
      </div>

      {tours.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No tours yet</CardTitle>
            <CardDescription>
              Start by creating a tour, then add the houses you plan to visit.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <p className="text-xs text-zinc-500">
            Swipe a tour left to delete it.
          </p>
          <div className="grid gap-3">
            {tours.map((tour) => (
              <SwipeableTourRow key={tour.id} tour={tour} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
