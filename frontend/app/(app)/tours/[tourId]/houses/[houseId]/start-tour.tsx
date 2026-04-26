"use client";

import { useMutation } from "@tanstack/react-query";
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
      <Button onClick={() => setOpen(true)}>Start tour</Button>

      <Modal open={open} onClose={close} title="How are you touring this house?">
        {mode === "picker" ? (
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => setMode("multi")}
              className="w-full text-left rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
            >
              <div className="font-medium">Multi-party (Zoom + bot)</div>
              <div className="text-sm text-zinc-600 dark:text-zinc-400 mt-1">
                Bot joins your Zoom meeting. Observations stream live to anyone
                watching from another device.
              </div>
            </button>
            <button
              type="button"
              onClick={() => setMode("solo")}
              className="w-full text-left rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition-colors"
            >
              <div className="font-medium">Solo (audio upload)</div>
              <div className="text-sm text-zinc-600 dark:text-zinc-400 mt-1">
                Record on your phone, upload after the tour. Observations and
                synthesis appear once processing finishes.
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
