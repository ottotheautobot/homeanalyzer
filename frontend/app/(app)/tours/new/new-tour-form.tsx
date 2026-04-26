"use client";

import { useActionState } from "react";

import { createTour } from "@/app/actions/tours";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function NewTourForm({
  defaultZoomUrl,
}: {
  defaultZoomUrl: string | null;
}) {
  const [state, formAction, pending] = useActionState(createTour, {});

  return (
    <form action={formAction} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="name">Tour name</Label>
        <Input
          id="name"
          name="name"
          placeholder="Fort Lauderdale, March"
          required
          disabled={pending}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="location">Location</Label>
        <Input
          id="location"
          name="location"
          placeholder="Fort Lauderdale, FL"
          disabled={pending}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="zoom_pmr_url">
          Zoom Personal Meeting Room URL{" "}
          <span className="text-zinc-500 font-normal">(optional)</span>
        </Label>
        <Input
          id="zoom_pmr_url"
          name="zoom_pmr_url"
          type="url"
          placeholder="https://zoom.us/j/..."
          defaultValue={defaultZoomUrl ?? ""}
          disabled={pending}
        />
        <p className="text-xs text-zinc-500">
          {defaultZoomUrl
            ? "Pre-filled from your account default. Leave as-is or override per tour."
            : "Only needed for multi-party tours where a Zoom bot joins. Solo (audio upload) tours don't need it."}
        </p>
      </div>
      {state?.error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{state.error}</p>
      ) : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Creating…" : "Create tour"}
      </Button>
    </form>
  );
}
