import Link from "next/link";

import { LiveRefresh } from "@/components/live-refresh";
import { RefreshOnVisibility } from "@/components/refresh-on-visibility";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { House, Tour, TourInvite } from "@/lib/types";

import { AddHouseButton } from "./add-house-button";
import { InviteForm } from "./invite-form";
import { InviteRow } from "./invite-row";
import { ShareControl } from "./share-control";
import { SwipeableHouseRow } from "./swipeable-house-row";
import { TourTabs } from "./tour-tabs";

export default async function TourPage({
  params,
}: {
  params: Promise<{ tourId: string }>;
}) {
  const { tourId } = await params;
  const [tour, houses, invites] = await Promise.all([
    serverFetch<Tour>(`/tours/${tourId}`),
    serverFetch<House[]>(`/tours/${tourId}/houses`),
    serverFetch<TourInvite[]>(`/tours/${tourId}/invites`).catch(
      () => [] as TourInvite[],
    ),
  ]);

  const housesTab =
    houses.length === 0 ? (
      <Card>
        <CardHeader>
          <CardTitle>No houses yet</CardTitle>
          <CardDescription>
            Add the first property to start collecting notes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AddHouseButton tourId={tour.id} variant="empty" />
        </CardContent>
      </Card>
    ) : (
      <div className="space-y-3">
        <p className="text-xs text-zinc-500">Swipe a house left to delete it.</p>
        <div className="grid gap-3">
          {houses.map((house) => (
            <SwipeableHouseRow key={house.id} tourId={tour.id} house={house} />
          ))}
        </div>
      </div>
    );

  const invitesTab = (
    <Card>
      <CardContent className="pt-6 space-y-4">
        <InviteForm tourId={tour.id} />
        {invites.length > 0 ? (
          <ul className="space-y-2 border-t border-zinc-200 dark:border-zinc-800 pt-3">
            {invites.map((inv) => (
              <InviteRow key={inv.id} invite={inv} />
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );

  const shareTab = (
    <Card>
      <CardContent className="pt-6">
        <ShareControl tourId={tour.id} />
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      <LiveRefresh
        channel={`tour-houses:${tour.id}`}
        table="houses"
        filter={`tour_id=eq.${tour.id}`}
      />
      <RefreshOnVisibility />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href="/tours"
            className="text-sm text-zinc-600 dark:text-zinc-400 hover:underline"
          >
            ← All tours
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight truncate">
            {tour.name}
          </h1>
          {tour.location ? (
            <p className="text-zinc-600 dark:text-zinc-400 truncate">
              {tour.location}
            </p>
          ) : null}
        </div>
        {houses.length > 0 ? (
          <div className="shrink-0 pt-6">
            <AddHouseButton tourId={tour.id} />
          </div>
        ) : null}
      </div>

      <TourTabs
        housesTab={housesTab}
        invitesTab={invitesTab}
        shareTab={shareTab}
        inviteCount={invites.length}
      />
    </div>
  );
}
