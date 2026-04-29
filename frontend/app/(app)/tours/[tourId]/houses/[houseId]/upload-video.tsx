"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import { createSupabaseBrowserClient } from "@/lib/supabase/browser";

type SignedUploadResponse = {
  signed_url: string;
  token: string;
  storage_path: string;
};

type ProcessResponse = {
  house_id: string;
  status: string;
  duration_seconds: number | null;
};

const STORAGE_BUCKET = "tour-audio";

function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i >= 0 ? filename.slice(i + 1).toLowerCase() : "mp4";
}

export function UploadVideo({ houseId }: { houseId: string }) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (file: File): Promise<ProcessResponse> => {
      // 1. Mint a signed upload URL from the backend.
      setProgress("Preparing upload…");
      const ext = extOf(file.name);
      const signed = await clientFetch<SignedUploadResponse>(
        `/houses/${houseId}/video/upload-url?ext=${encodeURIComponent(ext)}`,
        { method: "POST" },
      );

      // 2. PUT the file directly to Supabase via the signed URL — no
      //    Railway proxy in this path, so multi-hundred-MB uploads work.
      setProgress(`Uploading ${(file.size / (1024 * 1024)).toFixed(0)} MB…`);
      const supabase = createSupabaseBrowserClient();
      const { error: uploadError } = await supabase.storage
        .from(STORAGE_BUCKET)
        .uploadToSignedUrl(signed.storage_path, signed.token, file, {
          contentType: file.type || `video/${ext}`,
          upsert: true,
        });
      if (uploadError) {
        throw new Error(uploadError.message || "Upload to storage failed");
      }

      // 3. Tell the backend the upload landed; it'll fetch + process.
      setProgress("Starting analysis…");
      const result = await clientFetch<ProcessResponse>(
        `/houses/${houseId}/video/process`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ storage_path: signed.storage_path }),
        },
      );
      return result;
    },
    onSuccess: () => {
      setProgress(null);
      router.refresh();
    },
    onError: () => {
      setProgress(null);
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
          {mutation.isPending ? (progress ?? "Uploading…") : "Upload video"}
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
