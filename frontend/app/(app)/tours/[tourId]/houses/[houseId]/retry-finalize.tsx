"use client";

import { Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

type RetryOut = {
  ok: boolean;
  detail: string;
  audio_url: string | null;
  video_url: string | null;
};

export function RetryFinalize({ houseId }: { houseId: string }) {
  const router = useRouter();
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<RetryOut | null>(null);

  const run = useMutation({
    mutationFn: () =>
      clientFetch<RetryOut>(`/houses/${houseId}/retry-finalize`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      setResult(data);
      if (data.ok) router.refresh();
    },
  });

  if (result?.ok) {
    return (
      <div className="rounded-md border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50 dark:bg-emerald-950/20 p-3 text-sm text-emerald-800 dark:text-emerald-200">
        {result.detail}
      </div>
    );
  }

  if (!confirmed) {
    return (
      <div className="rounded-md border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/20 p-3 space-y-2">
        <p className="text-sm">
          <span className="font-medium">Tour didn&apos;t fully process.</span>{" "}
          The bot recorded but the post-tour pipeline failed. Recovery is only
          possible while Meeting BaaS still has the recording (~4 hours after
          the tour ended).
        </p>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setConfirmed(true)}
        >
          <RotateCcw className="size-3.5 mr-1.5" />
          Try to recover
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/20 p-3 space-y-2">
      <p className="text-sm">
        Re-fetches the recording from Meeting BaaS, re-runs Whisper + synthesis
        + vision + auto-trigger Modal. Costs a few cents in API spend.
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => run.mutate()}
          disabled={run.isPending}
        >
          {run.isPending ? (
            <Loader2 className="size-3.5 mr-1.5 animate-spin" />
          ) : null}
          {run.isPending ? "Recovering…" : "Confirm"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setConfirmed(false)}
          disabled={run.isPending}
        >
          Cancel
        </Button>
      </div>
      {result && !result.ok ? (
        <p className="text-xs text-red-700 dark:text-red-300">
          {result.detail}
        </p>
      ) : null}
      {run.isError ? (
        <p className="text-xs text-red-700 dark:text-red-300">
          {run.error instanceof Error ? run.error.message : "Recovery failed"}
        </p>
      ) : null}
    </div>
  );
}
