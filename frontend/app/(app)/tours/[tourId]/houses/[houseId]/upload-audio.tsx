"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

type UploadResponse = {
  house_id: string;
  status: string;
  storage_path: string;
};

export function UploadAudio({ houseId }: { houseId: string }) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (file: File): Promise<UploadResponse> => {
      const fd = new FormData();
      fd.append("audio", file, file.name);
      return clientFetch<UploadResponse>(`/houses/${houseId}/audio`, {
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
          accept="audio/*"
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
          onClick={() => fileRef.current?.click()}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Uploading…" : "Upload audio"}
        </Button>
        {filename ? (
          <span className="text-sm text-zinc-600 dark:text-zinc-400 truncate">
            {filename}
          </span>
        ) : null}
      </div>
      {mutation.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {mutation.error instanceof Error
            ? mutation.error.message
            : "Upload failed"}
        </p>
      ) : null}
      {mutation.isSuccess ? (
        <p className="text-sm text-emerald-600 dark:text-emerald-400">
          Uploaded. Transcribing and extracting observations — they&apos;ll
          appear below as they&apos;re ready.
        </p>
      ) : null}
    </div>
  );
}
