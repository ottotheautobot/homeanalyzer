"use client";

import { useMutation } from "@tanstack/react-query";
import { Mic, Play, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { clientFetch } from "@/lib/api-client";
import type { House } from "@/lib/types";

import { UploadAudio } from "./upload-audio";

type Mode = "picker" | "solo" | "multi";

export function StartTour({
  houseId,
  defaultZoomUrl,
}: {
  houseId: string;
  defaultZoomUrl: string | null;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("picker");
  const [zoomUrl, setZoomUrl] = useState(defaultZoomUrl ?? "");

  const start = useMutation({
    mutationFn: async (): Promise<House> =>
      clientFetch<House>(`/houses/${houseId}/start_tour`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zoom_url: zoomUrl || null }),
      }),
    onSuccess: () => {
      setOpen(false);
      router.refresh();
    },
  });

  function close() {
    setOpen(false);
    setMode("picker");
    start.reset();
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} size="lg" className="w-full">
        <Play className="size-4 mr-1.5" fill="currentColor" />
        Start tour
      </Button>

      <Modal open={open} onClose={close} title="How are you touring this house?">
        {mode === "picker" ? (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setMode("multi")}
              className="w-full flex items-start gap-3 text-left rounded-lg border border-zinc-200 dark:border-zinc-800 p-3.5 hover:border-primary/50 hover:bg-primary/5 transition-colors"
            >
              <span className="shrink-0 inline-flex items-center justify-center size-9 rounded-md bg-primary/10 text-primary">
                <Users className="size-4.5" strokeWidth={2} />
              </span>
              <div className="min-w-0">
                <div className="font-medium leading-tight">Multi-party</div>
                <div className="text-xs text-zinc-600 dark:text-zinc-400 mt-1 leading-snug">
                  Bot joins Zoom. Observations stream live to anyone watching
                  remotely.
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => setMode("solo")}
              className="w-full flex items-start gap-3 text-left rounded-lg border border-zinc-200 dark:border-zinc-800 p-3.5 hover:border-primary/50 hover:bg-primary/5 transition-colors"
            >
              <span className="shrink-0 inline-flex items-center justify-center size-9 rounded-md bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                <Mic className="size-4.5" strokeWidth={2} />
              </span>
              <div className="min-w-0">
                <div className="font-medium leading-tight">Solo</div>
                <div className="text-xs text-zinc-600 dark:text-zinc-400 mt-1 leading-snug">
                  Record on your phone, upload after. Brief generates once
                  processing finishes.
                </div>
              </div>
            </button>
          </div>
        ) : null}

        {mode === "multi" ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="zoom-url">Zoom meeting URL</Label>
              <Input
                id="zoom-url"
                value={zoomUrl}
                onChange={(e) => setZoomUrl(e.target.value)}
                placeholder="https://zoom.us/j/..."
              />
              <p className="text-xs text-zinc-500">
                Bot will join silently as &ldquo;Tour Notes&rdquo;.
              </p>
            </div>
            {start.isError ? (
              <p className="text-sm text-red-600 dark:text-red-400">
                {start.error instanceof Error
                  ? start.error.message
                  : "Failed to start tour"}
              </p>
            ) : null}
            <div className="flex gap-2 justify-end">
              <Button variant="ghost" onClick={() => setMode("picker")}>
                Back
              </Button>
              <Button
                onClick={() => start.mutate()}
                disabled={!zoomUrl || start.isPending}
              >
                {start.isPending ? "Sending bot…" : "Start tour"}
              </Button>
            </div>
          </div>
        ) : null}

        {mode === "solo" ? (
          <div className="space-y-4">
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Pick the audio file once you&apos;re back from the tour.
            </p>
            <UploadAudio houseId={houseId} />
            <div className="flex justify-end">
              <Button variant="ghost" onClick={() => setMode("picker")}>
                Back
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
