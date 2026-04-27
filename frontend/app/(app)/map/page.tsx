import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";

import { HousesMap } from "./houses-map";

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

export default async function MapPage() {
  // First load can be slow because Nominatim is rate-limited at ~1 req/s
  // for any rows missing coords. Subsequent loads are fast (cached).
  const pins = await serverFetch<HouseMapPin[]>("/houses/map");

  if (pins.length === 0) {
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
            <CardTitle className="text-base">No locatable houses</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-zinc-500">
              Add houses with full street addresses (city + state helps).
              Locations are auto-resolved on first view.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Map</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {pins.length} {pins.length === 1 ? "house" : "houses"} pinned. Tap a
          marker to jump to its brief.
        </p>
      </div>
      <HousesMap pins={pins} />
    </div>
  );
}
