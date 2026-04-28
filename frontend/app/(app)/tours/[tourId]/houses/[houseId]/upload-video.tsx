"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

type UploadResponse = {
  house_id: string;
  status: string;
  video_storage_path: string;
  duration_seconds: number | null;
};

export function UploadVideo({ houseId }: { houseId: string }) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (file: File): Promise<UploadResponse> => {
      const fd = new FormData();
      fd.append("video", file, file.name);
      return clientFetch<UploadResponse>(`/houses/${houseId}/video`, {
        method: "POST",
        body: fd,
      });
    },
    onSuccess: () => {
      router.refresh();
    },
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm,.mkv"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setFilename(file.name);
            mutation.mutate(file);
          }}
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => fileRef.current?.click()}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Uploading…" : "Upload video"}
        </Button>
        {filename ? (
          <span className="text-sm text-zinc-600 dark:text-zinc-400 truncate">
            {filename}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-zinc-500">
        For tours where the live path didn&apos;t work — uploads the recorded
        video, runs vision on the frames, transcribes the audio, and generates
        a brief + measured floor plan.
      </p>
      {mutation.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {mutation.error instanceof Error
            ? mutation.error.message
            : "Upload failed"}
        </p>
      ) : null}
      {mutation.isSuccess ? (
        <p className="text-sm text-emerald-600 dark:text-emerald-400">
          Uploaded
          {mutation.data.duration_seconds
            ? ` (${Math.round(mutation.data.duration_seconds / 60)} min)`
            : ""}
          . Vision + transcript pipelines running — observations and brief
          will appear below as they&apos;re ready.
        </p>
      ) : null}
    </div>
  );
}
