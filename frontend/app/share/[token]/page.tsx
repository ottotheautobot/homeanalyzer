import Link from "next/link";
import { notFound } from "next/navigation";

import { Synthesis } from "@/app/(app)/tours/[tourId]/houses/[houseId]/synthesis";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type SharedHouse = {
  id: string;
  address: string;
  list_price: number | null;
  price_kind: "buy" | "rent" | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  photo_signed_url: string | null;
  status: string;
  overall_score: number | null;
  synthesis_md: string | null;
};

type SharedObservation = {
  id: string;
  room: string | null;
  category: string;
  content: string;
  severity: string | null;
};

type SharedTour = {
  tour_id: string;
  name: string;
  location: string | null;
  status: string;
  shared_at: string;
  houses: SharedHouse[];
  observations_by_house: Record<string, SharedObservation[]>;
};

function formatPrice(n: number | null, kind: SharedHouse["price_kind"]) {
  if (n == null) return null;
  const dollars = n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
  return kind === "rent" ? `${dollars}/mo` : dollars;
}

async function fetchShare(token: string): Promise<SharedTour | null> {
  const res = await fetch(`${BACKEND_URL}/share/${encodeURIComponent(token)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return (await res.json()) as SharedTour;
}

export default async function SharePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const tour = await fetchShare(token);
  if (!tour) return notFound();

  const completedHouses = tour.houses.filter((h) => h.synthesis_md);
  const otherHouses = tour.houses.filter((h) => !h.synthesis_md);

  return (
    <div className="min-h-screen bg-white dark:bg-zinc-950">
      <div className="mx-auto max-w-4xl px-4 py-8 space-y-8">
        <header className="space-y-1">
          <p className="text-xs uppercase tracking-wide text-zinc-500">
            Shared tour
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{tour.name}</h1>
          {tour.location ? (
            <p className="text-zinc-600 dark:text-zinc-400">{tour.location}</p>
          ) : null}
          <p className="text-xs text-zinc-500">
            Read-only view. {tour.houses.length} houses ·{" "}
            {completedHouses.length} with briefs
          </p>
        </header>

        {completedHouses.length === 0 ? (
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-zinc-500">
                No completed houses to show yet.
              </p>
            </CardContent>
          </Card>
        ) : null}

        {completedHouses.map((h) => {
          const price = formatPrice(h.list_price, h.price_kind);
          const meta = [
            price,
            h.beds != null ? `${h.beds} bd` : null,
            h.baths != null ? `${h.baths} ba` : null,
            h.sqft != null ? `${h.sqft.toLocaleString()} sqft` : null,
          ]
            .filter(Boolean)
            .join(" · ");
          const obs = tour.observations_by_house[h.id] ?? [];
          return (
            <Card key={h.id}>
              <CardHeader className="flex flex-row items-start gap-3">
                {h.photo_signed_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={h.photo_signed_url}
                    alt={h.address}
                    className="size-16 rounded-md object-cover shrink-0"
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <CardTitle className="text-base">{h.address}</CardTitle>
                  {meta ? (
                    <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-0.5">
                      {meta}
                    </p>
                  ) : null}
                  {h.overall_score != null ? (
                    <p className="text-xs text-zinc-500 mt-0.5">
                      Score{" "}
                      <span className="font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                        {h.overall_score.toFixed(1)}
                      </span>
                    </p>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {h.synthesis_md ? (
                  <Synthesis markdown={h.synthesis_md} />
                ) : null}
                {obs.length > 0 ? (
                  <details className="text-sm">
                    <summary className="cursor-pointer font-medium text-zinc-700 dark:text-zinc-300">
                      Observations ({obs.length})
                    </summary>
                    <ul className="mt-2 space-y-1.5 text-xs">
                      {obs.map((o) => (
                        <li
                          key={o.id}
                          className="border-l-2 border-zinc-200 dark:border-zinc-800 pl-2"
                        >
                          {o.room ? (
                            <span className="capitalize text-zinc-500 mr-1.5">
                              {o.room}:
                            </span>
                          ) : null}
                          <span>{o.content}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </CardContent>
            </Card>
          );
        })}

        {otherHouses.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Not toured yet</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                {otherHouses.map((h) => (
                  <li key={h.id}>{h.address}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ) : null}

        <footer className="pt-4 text-center text-xs text-zinc-500">
          <Link href="/" className="hover:underline">
            HomeAnalyzer
          </Link>
        </footer>
      </div>
    </div>
  );
}
