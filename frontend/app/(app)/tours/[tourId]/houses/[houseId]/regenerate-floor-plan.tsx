"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { House } from "@/lib/types";

export function RegenerateFloorPlan({
  houseId,
  hasPlan,
}: {
  houseId: string;
  hasPlan: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await clientFetch<House>(`/houses/${houseId}/regenerate-floorplan`, {
        method: "POST",
      });
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button onClick={run} disabled={busy} variant="secondary" size="sm">
        {busy
          ? "Generating…"
          : hasPlan
            ? "Regenerate layout"
            : "Generate layout"}
      </Button>
      {error ? <span className="text-xs text-red-600">{error}</span> : null}
    </div>
  );
}
