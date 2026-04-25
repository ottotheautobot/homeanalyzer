"use client";

import { useActionState, useEffect, useRef } from "react";

import { createHouse } from "@/app/actions/houses";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function NewHouseForm({ tourId }: { tourId: string }) {
  const action = createHouse.bind(null, tourId);
  const [state, formAction, pending] = useActionState(action, {});
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state?.ok) formRef.current?.reset();
  }, [state]);

  return (
    <form ref={formRef} action={formAction} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="address">Address</Label>
          <Input
            id="address"
            name="address"
            placeholder="123 Sea Breeze Ln, Fort Lauderdale, FL"
            required
            disabled={pending}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="list_price">List price</Label>
          <Input
            id="list_price"
            name="list_price"
            inputMode="numeric"
            placeholder="850000"
            disabled={pending}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="sqft">Sqft</Label>
          <Input
            id="sqft"
            name="sqft"
            inputMode="numeric"
            placeholder="1850"
            disabled={pending}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="beds">Beds</Label>
          <Input
            id="beds"
            name="beds"
            inputMode="decimal"
            placeholder="3"
            disabled={pending}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="baths">Baths</Label>
          <Input
            id="baths"
            name="baths"
            inputMode="decimal"
            placeholder="2.5"
            disabled={pending}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="listing_url">Listing URL</Label>
          <Input
            id="listing_url"
            name="listing_url"
            type="url"
            placeholder="https://www.zillow.com/..."
            disabled={pending}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="scheduled_at">Scheduled tour time</Label>
          <Input
            id="scheduled_at"
            name="scheduled_at"
            type="datetime-local"
            disabled={pending}
          />
        </div>
      </div>
      {state?.error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{state.error}</p>
      ) : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Adding…" : "Add house"}
      </Button>
    </form>
  );
}
