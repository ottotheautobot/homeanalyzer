"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type { TourInvite } from "@/lib/types";

const ROLE_LABEL: Record<string, string> = {
  buyer: "Buyer",
  partner: "Partner",
  agent: "Agent",
  friend_family: "Friend / family",
};

export function InviteRow({ invite }: { invite: TourInvite }) {
  const router = useRouter();
  const del = useMutation({
    mutationFn: async () => {
      await clientFetch(`/tours/${invite.tour_id}/invites/${invite.id}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => router.refresh(),
  });

  return (
    <li className="flex items-center justify-between text-sm gap-3">
      <span className="font-medium truncate">{invite.email}</span>
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-xs text-zinc-500">
          {invite.role ? ROLE_LABEL[invite.role] ?? invite.role : "—"}
          {" · "}
          <span className="uppercase tracking-wide">
            {invite.accepted_at ? "joined" : "pending"}
          </span>
        </span>
        {!invite.accepted_at ? (
          <Button
            variant="ghost"
            size="xs"
            onClick={() => del.mutate()}
            disabled={del.isPending}
            aria-label={`Delete invite for ${invite.email}`}
          >
            {del.isPending ? "…" : "✕"}
          </Button>
        ) : null}
      </div>
    </li>
  );
}
