import Link from "next/link";

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

const STATUS_TONE: Record<House["status"], string> = {
  upcoming: "text-zinc-500",
  touring: "text-amber-600 dark:text-amber-400",
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
          <div className="grid gap-3">
            {houses.map((house) => {
              const price = formatPrice(house.list_price);
              return (
                <Link
                  key={house.id}
                  href={`/tours/${tour.id}/houses/${house.id}`}
                  className="block rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <div>
                      <div className="font-medium">{house.address}</div>
                      <div className="text-sm text-zinc-600 dark:text-zinc-400">
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
                      className={`text-xs uppercase tracking-wide ${STATUS_TONE[house.status]}`}
                    >
                      {house.status}
                      {house.overall_score != null
                        ? ` · ${house.overall_score.toFixed(1)}`
                        : ""}
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
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
