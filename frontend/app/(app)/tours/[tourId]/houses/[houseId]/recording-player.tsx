"use client";

import { Film } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { clientFetch } from "@/lib/api-client";

type MediaUrls = {
  audio_url: string | null;
  video_url: string | null;
};

export function RecordingPlayer({ houseId }: { houseId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["media", houseId],
    queryFn: () => clientFetch<MediaUrls>(`/houses/${houseId}/media`),
    staleTime: 50 * 60 * 1000, // signed URLs are valid 60 min; refresh just before
  });

  if (isLoading) {
    return (
      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-900 aspect-video animate-pulse flex items-center justify-center gap-2 text-sm text-zinc-500">
        <Film className="size-4" />
        Loading recording…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 px-4 py-6 text-sm text-zinc-500 text-center">
        Couldn&apos;t load the recording.
      </div>
    );
  }
  if (!data.video_url && !data.audio_url) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 px-4 py-6 text-sm text-zinc-500 text-center flex items-center justify-center gap-2">
        <Film className="size-4" />
        No recording archived for this tour.
      </div>
    );
  }
  if (data.video_url) {
    return (
      <video
        src={data.video_url}
        controls
        playsInline
        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-black aspect-video"
      />
    );
  }
  return (
    <audio
      src={data.audio_url ?? undefined}
      controls
      className="w-full"
    />
  );
}
