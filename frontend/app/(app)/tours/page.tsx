import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { Tour } from "@/lib/types";

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
        <div className="grid gap-3">
          {tours.map((tour) => (
            <Link
              key={tour.id}
              href={`/tours/${tour.id}`}
              className="block rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
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
          ))}
        </div>
      )}
    </div>
  );
}
