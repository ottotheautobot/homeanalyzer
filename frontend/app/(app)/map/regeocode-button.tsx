"use client";

import { Loader2, RefreshCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

export function RegeocodeButton() {
  const router = useRouter();
  const [confirmed, setConfirmed] = useState(false);

  const run = useMutation({
    mutationFn: () =>
      clientFetch<{ cleared: number }>("/houses/regeocode", { method: "POST" }),
    onSuccess: () => {
      setConfirmed(false);
      router.refresh();
    },
  });

  if (!confirmed) {
    return (
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => setConfirmed(true)}
      >
        <RefreshCcw className="size-3.5 mr-1.5" />
        Re-check addresses
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-zinc-600 dark:text-zinc-400">
        Clears all cached coordinates and re-runs validation. Pins reappear as
        addresses resolve.
      </span>
      <Button
        type="button"
        size="sm"
        onClick={() => run.mutate()}
        disabled={run.isPending}
      >
        {run.isPending ? (
          <Loader2 className="size-3.5 mr-1.5 animate-spin" />
        ) : null}
        Confirm
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
  );
}
