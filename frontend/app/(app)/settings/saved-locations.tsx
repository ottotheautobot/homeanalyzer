"use client";

import { Briefcase, Dumbbell, GraduationCap, Heart, Loader2, MapPin, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { clientFetch } from "@/lib/api-client";
import type { SavedLocation } from "@/lib/types";

type GeocodeResponse = { address: string; lat: number; lng: number };
type NewIdResponse = { id: string };
type MeShape = {
  saved_locations: SavedLocation[];
};

const KIND_OPTIONS: { value: SavedLocation["kind"]; label: string }[] = [
  { value: "work", label: "Work" },
  { value: "school", label: "School" },
  { value: "gym", label: "Gym" },
  { value: "family", label: "Family" },
  { value: "other", label: "Other" },
];

function kindIcon(kind: SavedLocation["kind"]) {
  switch (kind) {
    case "work":
      return <Briefcase className="size-3.5" strokeWidth={2.2} />;
    case "school":
      return <GraduationCap className="size-3.5" strokeWidth={2.2} />;
    case "gym":
      return <Dumbbell className="size-3.5" strokeWidth={2.2} />;
    case "family":
      return <Heart className="size-3.5" strokeWidth={2.2} />;
    default:
      return <MapPin className="size-3.5" strokeWidth={2.2} />;
  }
}

export function SavedLocationsForm({
  initial,
}: {
  initial: SavedLocation[];
}) {
  const [locations, setLocations] = useState<SavedLocation[]>(initial);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftAddress, setDraftAddress] = useState("");
  const [draftKind, setDraftKind] = useState<SavedLocation["kind"]>("other");
  const [error, setError] = useState<string | null>(null);

  const persist = useMutation({
    mutationFn: async (next: SavedLocation[]): Promise<MeShape> =>
      clientFetch<MeShape>("/me", {
        method: "PATCH",
        body: JSON.stringify({ saved_locations: next }),
      }),
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : "Failed to save");
    },
    onSuccess: () => setError(null),
  });

  const add = useMutation({
    mutationFn: async (): Promise<SavedLocation> => {
      if (!draftLabel.trim() || !draftAddress.trim()) {
        throw new Error("Both label and address are required.");
      }
      const [{ id }, geo] = await Promise.all([
        clientFetch<NewIdResponse>("/me/saved-locations/new-id", {
          method: "POST",
        }),
        clientFetch<GeocodeResponse>("/me/saved-locations/geocode", {
          method: "POST",
          body: JSON.stringify({ address: draftAddress.trim() }),
        }),
      ]);
      return {
        id,
        label: draftLabel.trim().slice(0, 60),
        address: geo.address,
        lat: geo.lat,
        lng: geo.lng,
        kind: draftKind,
      };
    },
    onSuccess: (loc) => {
      const next = [...locations, loc];
      setLocations(next);
      setDraftLabel("");
      setDraftAddress("");
      setDraftKind("other");
      setError(null);
      persist.mutate(next);
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : "Couldn't add location");
    },
  });

  function remove(id: string) {
    const next = locations.filter((l) => l.id !== id);
    setLocations(next);
    persist.mutate(next);
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-500">
        Pin places that matter — work, the kids&apos; school, the gym — and
        every house on the map will show how far it is from each one.
      </p>

      {locations.length > 0 ? (
        <ul className="space-y-1.5">
          {locations.map((loc) => (
            <li
              key={loc.id}
              className="flex items-center gap-3 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-2"
            >
              <span className="shrink-0 inline-flex items-center justify-center size-7 rounded-md bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                {kindIcon(loc.kind)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium leading-tight truncate">
                  {loc.label}
                </div>
                {loc.address ? (
                  <div className="text-xs text-zinc-500 truncate">
                    {loc.address}
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => remove(loc.id)}
                className="text-zinc-400 hover:text-red-500 transition-colors"
                aria-label={`Remove ${loc.label}`}
              >
                <Trash2 className="size-4" strokeWidth={2} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-zinc-400">
          No saved locations yet. Add one below.
        </p>
      )}

      <div className="rounded-lg border border-dashed border-zinc-200 dark:border-zinc-800 p-3 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="loc-label">Label</Label>
            <Input
              id="loc-label"
              placeholder="Work, Lila's school, the gym…"
              value={draftLabel}
              onChange={(e) => setDraftLabel(e.target.value)}
              maxLength={60}
              disabled={add.isPending}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loc-kind">Kind</Label>
            <select
              id="loc-kind"
              value={draftKind}
              onChange={(e) =>
                setDraftKind(e.target.value as SavedLocation["kind"])
              }
              disabled={add.isPending}
              className="flex h-9 w-full rounded-md border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            >
              {KIND_OPTIONS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="loc-address">Address</Label>
          <Input
            id="loc-address"
            placeholder="123 Main St, Fort Lauderdale, FL"
            value={draftAddress}
            onChange={(e) => setDraftAddress(e.target.value)}
            maxLength={300}
            disabled={add.isPending}
          />
        </div>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            onClick={() => add.mutate()}
            disabled={
              add.isPending || !draftLabel.trim() || !draftAddress.trim()
            }
          >
            {add.isPending ? (
              <Loader2 className="size-4 mr-1.5 animate-spin" />
            ) : (
              <Plus className="size-4 mr-1" strokeWidth={2.5} />
            )}
            Add
          </Button>
          {error ? (
            <p className="text-xs text-red-600 dark:text-red-400 inline-flex items-center gap-1">
              <X className="size-3" /> {error}
            </p>
          ) : null}
          {persist.isPending ? (
            <span className="text-xs text-zinc-500">Saving…</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
