"use client";

import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { House, Tour } from "@/lib/types";

import { Synthesis } from "../tours/[tourId]/houses/[houseId]/synthesis";

type CompareResponse = {
  answer: string;
  used_house_ids: string[];
};

const SUGGESTIONS = [
  "Rank these by overall fit for a young family.",
  "Which house had the best kitchen?",
  "What are the biggest hazards across the houses I'm considering?",
  "Which had the most concerning condition issues?",
  "If I had to pick one tomorrow, which would you choose and why?",
];

export function CompareForm({
  houses,
  tourById,
}: {
  houses: House[];
  tourById: Record<string, Tour>;
}) {
  const [selected, setSelected] = useState<Set<string>>(
    new Set(houses.slice(0, Math.min(houses.length, 5)).map((h) => h.id)),
  );
  const [query, setQuery] = useState("");

  const ask = useMutation({
    mutationFn: async (): Promise<CompareResponse> =>
      clientFetch<CompareResponse>("/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          house_ids: Array.from(selected),
          query: query.trim(),
        }),
      }),
  });

  const grouped = useMemo(() => {
    const byTour: Record<string, House[]> = {};
    for (const h of houses) {
      const tid = h.tour_id;
      (byTour[tid] ||= []).push(h);
    }
    return Object.entries(byTour).map(([tid, list]) => ({
      tour: tourById[tid],
      houses: list,
    }));
  }, [houses, tourById]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-lg font-medium">Houses</h2>
        <div className="space-y-4">
          {grouped.map(({ tour, houses }) => (
            <div key={tour?.id ?? "unknown"}>
              <div className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
                {tour?.name ?? "(unknown tour)"}
                {tour?.location ? ` · ${tour.location}` : ""}
              </div>
              <div className="grid gap-2">
                {houses.map((h) => {
                  const checked = selected.has(h.id);
                  return (
                    <label
                      key={h.id}
                      className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer transition-colors ${
                        checked
                          ? "border-zinc-400 dark:border-zinc-600 bg-zinc-50 dark:bg-zinc-900"
                          : "border-zinc-200 dark:border-zinc-800"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(h.id)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="font-medium">{h.address}</div>
                        <div className="text-sm text-zinc-600 dark:text-zinc-400">
                          {[
                            h.list_price != null
                              ? `$${h.list_price.toLocaleString()}`
                              : null,
                            h.beds != null ? `${h.beds} bd` : null,
                            h.baths != null ? `${h.baths} ba` : null,
                            h.sqft != null
                              ? `${h.sqft.toLocaleString()} sqft`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </div>
                      {h.overall_score != null ? (
                        <span className="text-xs uppercase tracking-wide text-zinc-500">
                          {h.overall_score.toFixed(1)}
                        </span>
                      ) : null}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Ask</h2>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={3}
          placeholder="Which house had the best kitchen for the kids?"
          className="w-full rounded-md border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-sm focus:outline-none focus:border-zinc-400 dark:focus:border-zinc-600"
        />
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setQuery(s)}
              className="text-xs rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-2 py-1 hover:border-zinc-400 dark:hover:border-zinc-600"
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Button
            onClick={() => ask.mutate()}
            disabled={!query.trim() || selected.size < 2 || ask.isPending}
          >
            {ask.isPending ? "Thinking…" : "Compare"}
          </Button>
          <span className="text-xs text-zinc-500">
            {selected.size} selected · {selected.size < 2 ? "pick at least 2" : "ready"}
          </span>
        </div>
      </section>

      {ask.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {ask.error instanceof Error ? ask.error.message : "Comparison failed"}
        </p>
      ) : null}

      {ask.data ? (
        <section className="space-y-3">
          <h2 className="text-lg font-medium">Answer</h2>
          <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4">
            <Synthesis markdown={ask.data.answer} />
          </div>
        </section>
      ) : null}
    </div>
  );
}
