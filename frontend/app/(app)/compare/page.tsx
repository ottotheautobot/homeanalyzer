import { serverFetch } from "@/lib/api-server";
import type { House, Tour } from "@/lib/types";

import { CompareForm } from "./compare-form";

export default async function ComparePage() {
  const [houses, tours] = await Promise.all([
    serverFetch<House[]>("/houses?status_eq=completed"),
    serverFetch<Tour[]>("/tours"),
  ]);

  const tourById = new Map(tours.map((t) => [t.id, t]));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Compare</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Pick the houses you want to compare across tours, then ask a
          question. Sonnet 4.6 reads every brief and observation in one pass.
        </p>
      </div>

      {houses.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No completed houses yet. Tour a couple and come back.
        </p>
      ) : (
        <CompareForm houses={houses} tourById={Object.fromEntries(tourById)} />
      )}
    </div>
  );
}
