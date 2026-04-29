import Link from "next/link";

import { LiveRefresh } from "@/components/live-refresh";
import { RefreshOnVisibility } from "@/components/refresh-on-visibility";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { House, Observation, Tour, Transcript } from "@/lib/types";

import { FloorPlanView } from "./floor-plan";
import { LiveTour } from "./live-tour";
import { ObservationFeed } from "./observation-feed";
import { PhotoNoteButton } from "./photo-note";
import { PhotoThumbnail } from "./photo-thumbnail";
import { RecordingPlayer } from "./recording-player";
import { RetryFinalize } from "./retry-finalize";
import { StartTour } from "./start-tour";
import { Synthesis } from "./synthesis";
import { TranscriptFeed } from "./transcript-feed";

const STATUS_PILL: Record<House["status"], { label: string; cls: string }> = {
  upcoming: {
    label: "Not toured",
    cls: "bg-zinc-100 dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400",
  },
  touring: {
    label: "Live",
    cls: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400",
  },
  synthesizing: {
    label: "Generating brief…",
    cls: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
  },
  completed: {
    label: "Brief ready",
    cls: "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400",
  },
};

function formatPrice(n: number | null, kind: House["price_kind"]) {
  if (n == null) return null;
  const dollars = n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
  return kind === "rent" ? `${dollars}/mo` : dollars;
}

export default async function HousePage({
  params,
}: {
  params: Promise<{ tourId: string; houseId: string }>;
}) {
  const { tourId, houseId } = await params;
  const [house, observations, tour, transcripts] = await Promise.all([
    serverFetch<House>(`/houses/${houseId}`),
    serverFetch<Observation[]>(`/houses/${houseId}/observations`),
    serverFetch<Tour>(`/tours/${tourId}`),
    serverFetch<Transcript[]>(`/houses/${houseId}/transcripts`).catch(
      () => [] as Transcript[],
    ),
  ]);

  const price = formatPrice(house.list_price, house.price_kind);
  const meta = [
    price,
    house.beds != null ? `${house.beds} bd` : null,
    house.baths != null ? `${house.baths} ba` : null,
    house.sqft != null ? `${house.sqft.toLocaleString()} sqft` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const isLiveMultiParty = house.status === "touring" && !!house.bot_id;

  return (
    <div className="space-y-5">
      <LiveRefresh
        channel={`house:${house.id}`}
        table="houses"
        filter={`id=eq.${house.id}`}
      />
      <RefreshOnVisibility />
      <div>
        <Link
          href={`/tours/${tourId}`}
          className="text-sm text-zinc-600 dark:text-zinc-400 hover:underline"
        >
          ← Tour
        </Link>
        <div className="mt-1 flex items-start justify-between gap-3">
          <div className="min-w-0 flex items-center gap-3">
            {house.photo_signed_url ? (
              <PhotoThumbnail src={house.photo_signed_url} />
            ) : null}
            <div className="min-w-0">
              <h1 className="text-base font-semibold tracking-tight leading-tight">
                {house.address}
              </h1>
              {meta ? (
                <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-0.5">
                  {meta}
                </p>
              ) : null}
            </div>
          </div>
          <div className="shrink-0 flex flex-col items-end gap-1.5">
            <span
              className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-md ${STATUS_PILL[house.status].cls}`}
            >
              {house.status === "touring" ? (
                <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
              ) : null}
              {STATUS_PILL[house.status].label}
            </span>
            {house.overall_score != null ? (
              <span className="text-xs text-zinc-500">
                Score{" "}
                <span className="font-semibold text-zinc-900 dark:text-zinc-100 tabular-nums">
                  {house.overall_score.toFixed(1)}
                </span>
              </span>
            ) : null}
            {house.tour_started_at ? (
              <span className="text-xs text-zinc-500">
                Toured{" "}
                {new Date(house.tour_started_at).toLocaleString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {isLiveMultiParty ? "Live tour" : "Tour"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLiveMultiParty ? (
            <LiveTour
              house={house}
              zoomUrl={tour.zoom_pmr_url}
              startedAt={house.tour_started_at}
            />
          ) : house.status === "upcoming" ? (
            <StartTour
              houseId={house.id}
              defaultZoomUrl={tour.zoom_pmr_url}
            />
          ) : (
            <p className="text-sm text-zinc-500">
              {house.status === "synthesizing"
                ? "Bot left the meeting. Generating the brief now — this usually takes about a minute."
                : "Tour complete."}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Recovery affordance: bot ran but post-meeting pipeline didn't
          land — no audio, no synthesis. Stuck rows usually sit at
          status=synthesizing (the original webhook crashed before flipping
          to completed) but we also catch completed-without-data. Surfaces
          retry-finalize, which only works while MB still has the recording. */}
      {house.bot_id &&
      (house.status === "synthesizing" ||
        (house.status === "completed" && !house.audio_url)) &&
      !house.synthesis_md ? (
        <RetryFinalize houseId={house.id} />
      ) : null}

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

      {house.status === "completed" ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Rooms</CardTitle>
          </CardHeader>
          <CardContent>
            <FloorPlanView plan={house.floor_plan_json} />
          </CardContent>
        </Card>
      ) : null}

      {house.status === "completed" &&
      ((house.video_url && (house.video_duration_seconds ?? 0) >= 30) ||
        (!house.video_url && house.audio_url)) ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 px-1">
            Recording
          </h2>
          <RecordingPlayer houseId={house.id} />
        </section>
      ) : null}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 px-1">Observations</h2>
        <PhotoNoteButton houseId={house.id} />
        <ObservationFeed houseId={house.id} initial={observations} />
      </section>

      {isLiveMultiParty ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 px-1">Live transcript</h2>
          <p className="text-xs text-zinc-500">
            Lines arrive as the bot hears them. Observations above populate
            every ~20s.
          </p>
          <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-4 max-h-72 overflow-y-auto">
            <TranscriptFeed houseId={house.id} initial={transcripts} />
          </div>
        </section>
      ) : null}
    </div>
  );
}
