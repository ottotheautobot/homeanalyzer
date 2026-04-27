"use client";

import { Check, Copy, Link as LinkIcon, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";

type ShareOut = {
  share_token: string | null;
  shared_at: string | null;
};

function buildShareUrl(token: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/share/${token}`;
}

export function ShareControl({ tourId }: { tourId: string }) {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);

  const status = useQuery({
    queryKey: ["share", tourId],
    queryFn: () => clientFetch<ShareOut>(`/tours/${tourId}/share`),
  });

  const create = useMutation({
    mutationFn: () =>
      clientFetch<ShareOut>(`/tours/${tourId}/share`, { method: "POST" }),
    onSuccess: (data) => qc.setQueryData(["share", tourId], data),
  });

  const revoke = useMutation({
    mutationFn: () =>
      clientFetch<ShareOut>(`/tours/${tourId}/share`, { method: "DELETE" }),
    onSuccess: (data) => qc.setQueryData(["share", tourId], data),
  });

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  const token = status.data?.share_token ?? null;
  const url = token ? buildShareUrl(token) : "";

  if (status.isPending) {
    return null;
  }

  if (!token) {
    return (
      <Button
        size="sm"
        variant="secondary"
        onClick={() => create.mutate()}
        disabled={create.isPending}
      >
        <LinkIcon className="size-4 mr-1.5" />
        {create.isPending ? "Creating…" : "Create share link"}
      </Button>
    );
  }

  return (
    <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 p-3 space-y-2">
      <div className="flex items-start gap-2">
        <LinkIcon className="size-4 mt-0.5 shrink-0 text-zinc-500" />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            Anyone with this link can read this tour&apos;s briefs (no login
            required). Revoke any time to invalidate.
          </p>
          <code className="block w-full overflow-x-auto rounded bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 px-2 py-1 text-xs">
            {url}
          </code>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            await navigator.clipboard.writeText(url);
            setCopied(true);
          }}
        >
          {copied ? (
            <>
              <Check className="size-4 mr-1.5" /> Copied
            </>
          ) : (
            <>
              <Copy className="size-4 mr-1.5" /> Copy link
            </>
          )}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => revoke.mutate()}
          disabled={revoke.isPending}
        >
          <X className="size-4 mr-1.5" />
          {revoke.isPending ? "Revoking…" : "Revoke"}
        </Button>
      </div>
    </div>
  );
}
