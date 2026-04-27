"use client";

import { Camera, Check, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

type PhotoObservationOut = {
  observations_added: number;
  photo_storage_path: string;
};

const ROOM_OPTIONS = [
  "kitchen",
  "living",
  "dining",
  "bedroom",
  "bathroom",
  "hallway",
  "entryway",
  "garage",
  "office",
  "laundry",
  "closet",
  "outdoor",
  "stairs",
];

export function PhotoNoteButton({ houseId }: { houseId: string }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [room, setRoom] = useState<string>("");
  const [lastResult, setLastResult] = useState<{
    added: number;
    at: number;
  } | null>(null);

  const upload = useMutation({
    mutationFn: async (file: File): Promise<PhotoObservationOut> => {
      const fd = new FormData();
      fd.append("photo", file);
      if (room) fd.append("room", room);
      return clientFetch<PhotoObservationOut>(
        `/houses/${houseId}/photo-observation`,
        { method: "POST", body: fd },
      );
    },
    onSuccess: (data) => {
      setLastResult({ added: data.observations_added, at: Date.now() });
      router.refresh();
    },
  });

  const showSuccess =
    lastResult && Date.now() - lastResult.at < 6000 && !upload.isPending;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
            e.target.value = "";
          }}
        />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => inputRef.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? (
            <Loader2 className="size-4 mr-1.5 animate-spin" />
          ) : (
            <Camera className="size-4 mr-1.5" />
          )}
          {upload.isPending ? "Analyzing…" : "Add photo note"}
        </Button>
        <select
          value={room}
          onChange={(e) => setRoom(e.target.value)}
          className="h-8 rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-xs px-2"
          aria-label="Room hint (optional)"
        >
          <option value="">Auto-detect room</option>
          {ROOM_OPTIONS.map((r) => (
            <option key={r} value={r} className="capitalize">
              {r}
            </option>
          ))}
        </select>
      </div>
      {showSuccess ? (
        <p className="text-xs text-emerald-600 dark:text-emerald-400 inline-flex items-center gap-1">
          <Check className="size-3.5" />
          Added {lastResult.added}{" "}
          {lastResult.added === 1 ? "observation" : "observations"} from photo.
        </p>
      ) : null}
      {upload.isError ? (
        <p className="text-xs text-red-600 dark:text-red-400">
          {upload.error instanceof Error ? upload.error.message : "Upload failed"}
        </p>
      ) : null}
    </div>
  );
}
