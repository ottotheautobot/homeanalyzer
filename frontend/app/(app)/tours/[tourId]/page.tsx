import Link from "next/link";

import { LiveRefresh } from "@/components/live-refresh";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { House, Tour } from "@/lib/types";

import { NewHouseForm } from "./new-house-form";
import { SwipeableHouseRow } from "./swipeable-house-row";

export default async function TourPage({
  params,
}: {
  params: Promise<{ tourId: string }>;
}) {
  const { tourId } = await params;
  const [tour, houses] = await Promise.all([
    serverFetch<Tour>(`/tours/${tourId}`),
    serverFetch<House[]>(`/tours/${tourId}/houses`),
  ]);

  return (
    <div className="space-y-8">
      <LiveRefresh
        channel={`tour-houses:${tour.id}`}
        table="houses"
        filter={`tour_id=eq.${tour.id}`}
      />
      <div>
        <Link
          href="/tours"
          className="text-sm text-zinc-600 dark:text-zinc-400 hover:underline"
        >
          ← All tours
        </Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {tour.name}
        </h1>
        {tour.location ? (
          <p className="text-zinc-600 dark:text-zinc-400">{tour.location}</p>
        ) : null}
      </div>

      <section className="space-y-4">
        <h2 className="text-lg font-medium">Houses</h2>
        {houses.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>No houses yet</CardTitle>
              <CardDescription>
                Add the first property below.
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <>
            <p className="text-xs text-zinc-500">
              Swipe a house left to delete it.
            </p>
            <div className="grid gap-3">
              {houses.map((house) => (
                <SwipeableHouseRow
                  key={house.id}
                  tourId={tour.id}
                  house={house}
                />
              ))}
            </div>
          </>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-medium">Add a house</h2>
        <Card>
          <CardContent className="pt-6">
            <NewHouseForm tourId={tour.id} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
