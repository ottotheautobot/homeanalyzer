"use client";

import { Loader2, Zap } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { clientFetch } from "@/lib/api-client";

type QuickResponse = {
  tour_id: string;
  house_id: string;
  tour_was_created: boolean;
};

export function QuickTourButton() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [address, setAddress] = useState("");

  const start = useMutation({
    mutationFn: async (): Promise<QuickResponse> =>
      clientFetch<QuickResponse>("/tours/quick", {
        method: "POST",
        body: JSON.stringify({ address: address.trim() }),
      }),
    onSuccess: (data) => {
      setOpen(false);
      setAddress("");
      router.push(`/tours/${data.tour_id}/houses/${data.house_id}`);
    },
  });

  return (
    <>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => setOpen(true)}
        className="gap-1.5"
      >
        <Zap className="size-4" strokeWidth={2.5} />
        <span>Quick tour</span>
      </Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Start a quick tour">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!start.isPending && address.trim().length > 3) start.mutate();
          }}
          className="space-y-3"
        >
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            Adds a house under your most recent tour (or starts a new one if
            it&apos;s been a week). You can edit the rest later.
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="qt-address">Address</Label>
            <Input
              id="qt-address"
              autoFocus
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="123 Main St, Fort Lauderdale FL"
              maxLength={300}
            />
          </div>
          {start.isError ? (
            <p className="text-xs text-red-600 dark:text-red-400">
              {start.error instanceof Error
                ? start.error.message
                : "Failed to start"}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setOpen(false)}
              disabled={start.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={start.isPending || address.trim().length < 4}
            >
              {start.isPending ? (
                <Loader2 className="size-4 mr-1.5 animate-spin" />
              ) : null}
              Start
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
