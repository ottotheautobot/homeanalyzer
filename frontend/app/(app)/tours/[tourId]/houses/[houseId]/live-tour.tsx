"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { House } from "@/lib/types";

export function LiveTour({
  house,
  zoomUrl,
}: {
  house: House;
  zoomUrl: string | null;
}) {
  const router = useRouter();

  const endTour = useMutation({
    mutationFn: async (): Promise<House> =>
      clientFetch<House>(`/houses/${house.id}/end_tour`, { method: "POST" }),
    onSuccess: () => router.refresh(),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <span className="inline-block size-2 rounded-full bg-emerald-500 animate-pulse" />
        <span className="font-medium text-emerald-700 dark:text-emerald-400">
          Bot in meeting
        </span>
      </div>

      {zoomUrl ? (
        <a
          href={zoomUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-sm rounded-md border border-zinc-200 dark:border-zinc-800 px-3 py-2 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
        >
          <div className="font-medium">Open Zoom meeting →</div>
          <div className="text-xs text-zinc-500 truncate">{zoomUrl}</div>
        </a>
      ) : null}

      <div className="pt-2">
        <Button
          variant="destructive"
          onClick={() => endTour.mutate()}
          disabled={endTour.isPending}
        >
          {endTour.isPending ? "Ending…" : "End tour"}
        </Button>
        {endTour.isError ? (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">
            {endTour.error instanceof Error
              ? endTour.error.message
              : "Failed to end tour"}
          </p>
        ) : null}
      </div>
    </div>
  );
}
