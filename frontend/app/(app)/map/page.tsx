import { RefreshOnVisibility } from "@/components/refresh-on-visibility";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";

import { HousesMap } from "./houses-map";
import { RegeocodeButton } from "./regeocode-button";

export type HouseMapPin = {
  id: string;
  tour_id: string;
  address: string;
  latitude: number;
  longitude: number;
  overall_score: number | null;
  status: string;
  photo_signed_url: string | null;
};

type HouseMapResponse = {
  pins: HouseMapPin[];
  total_houses: number;
  pending_geocode: number;
};

export default async function MapPage() {
  // The backend caps synchronous geocoding to a few houses per request and
  // pushes the rest into background tasks; we refresh on visibility so the
  // map fills in without a hard reload.
  const data = await serverFetch<HouseMapResponse>("/houses/map");
  const { pins, total_houses, pending_geocode } = data;

  if (total_houses === 0) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Map</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Geographic view of every house across your tours.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">No houses yet</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-500">
              Add a house from a tour and it&apos;ll appear here.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (pins.length === 0) {
    return (
      <div className="space-y-5">
        <RefreshOnVisibility />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Map</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Resolving {total_houses}{" "}
            {total_houses === 1 ? "address" : "addresses"} to coordinates…
            this page auto-refreshes when you come back to it.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Geocoding in progress</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-500">
              First load only — coordinates cache afterwards. Try refreshing in
              ~{Math.max(15, total_houses * 2)} seconds.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const partial = pending_geocode > 0;

  return (
    <div className="space-y-5">
      {partial ? <RefreshOnVisibility /> : null}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">Map</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {pins.length} of {total_houses}{" "}
            {total_houses === 1 ? "house" : "houses"} pinned. Tap a marker to
            jump to its brief.
          </p>
          {partial ? (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
              Resolving {pending_geocode} more{" "}
              {pending_geocode === 1 ? "address" : "addresses"} in the
              background — refresh in a few seconds.
            </p>
          ) : null}
        </div>
        <RegeocodeButton />
      </div>
      <HousesMap pins={pins} />
    </div>
  );
}
