import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { House, Observation } from "@/lib/types";

import { ObservationFeed } from "./observation-feed";
import { Synthesis } from "./synthesis";
import { UploadAudio } from "./upload-audio";

const STATUS_LABEL: Record<House["status"], string> = {
  upcoming: "Not yet toured",
  touring: "Processing audio…",
  completed: "Synthesis ready",
};

function formatPrice(n: number | null) {
  if (n == null) return null;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export default async function HousePage({
  params,
}: {
  params: Promise<{ tourId: string; houseId: string }>;
}) {
  const { tourId, houseId } = await params;
  const [house, observations] = await Promise.all([
    serverFetch<House>(`/houses/${houseId}`),
    serverFetch<Observation[]>(`/houses/${houseId}/observations`),
  ]);

  const price = formatPrice(house.list_price);
  const meta = [
    price,
    house.beds != null ? `${house.beds} bd` : null,
    house.baths != null ? `${house.baths} ba` : null,
    house.sqft != null ? `${house.sqft.toLocaleString()} sqft` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-8">
      <div>
        <Link
          href={`/tours/${tourId}`}
          className="text-sm text-zinc-600 dark:text-zinc-400 hover:underline"
        >
          ← Tour
        </Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {house.address}
        </h1>
        {meta ? (
          <p className="text-zinc-600 dark:text-zinc-400">{meta}</p>
        ) : null}
        <p className="mt-1 text-xs uppercase tracking-wide text-zinc-500">
          {STATUS_LABEL[house.status]}
          {house.overall_score != null
            ? ` · score ${house.overall_score.toFixed(1)}`
            : ""}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Audio</CardTitle>
        </CardHeader>
        <CardContent>
          <UploadAudio houseId={house.id} />
        </CardContent>
      </Card>

      {house.synthesis_md ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Synthesis</CardTitle>
          </CardHeader>
          <CardContent>
            <Synthesis markdown={house.synthesis_md} />
          </CardContent>
        </Card>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Observations</h2>
        <ObservationFeed houseId={house.id} initial={observations} />
      </section>
    </div>
  );
}
