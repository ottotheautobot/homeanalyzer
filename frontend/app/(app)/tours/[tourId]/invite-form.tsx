"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { clientFetch } from "@/lib/api-client";

type Role = "partner" | "agent" | "buyer" | "friend_family";

export function InviteForm({ tourId }: { tourId: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("partner");

  const send = useMutation({
    mutationFn: async (): Promise<unknown> =>
      clientFetch(`/tours/${tourId}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, role }),
      }),
    onSuccess: () => {
      setEmail("");
      router.refresh();
    },
  });

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto] items-end">
        <div className="space-y-1.5">
          <Label htmlFor="invite-email">Email</Label>
          <Input
            id="invite-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="partner@example.com"
            disabled={send.isPending}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="invite-role">Role</Label>
          <select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="h-8 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-2 text-sm"
            disabled={send.isPending}
          >
            <option value="partner">Partner</option>
            <option value="friend_family">Friend / family</option>
            <option value="agent">Agent</option>
            <option value="buyer">Buyer</option>
          </select>
        </div>
        <Button
          onClick={() => send.mutate()}
          disabled={!email || send.isPending}
        >
          {send.isPending ? "Sending…" : "Send invite"}
        </Button>
      </div>
      {send.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          {send.error instanceof Error ? send.error.message : "Send failed"}
        </p>
      ) : null}
      {send.isSuccess ? (
        <p className="text-sm text-emerald-600 dark:text-emerald-400">
          Sent. They&apos;ll get a magic-link email.
        </p>
      ) : null}
    </div>
  );
}
