"use client";

import { Briefcase, Dumbbell, GraduationCap, Heart, MapPin } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Map, Overlay, ZoomControl } from "pigeon-maps";

import type { CommuteEntry, SavedLocation } from "@/lib/types";

import type { HouseMapPin } from "./page";

// Carto Voyager basemap — modern OSM-derived styling, free for non-commercial
// use with attribution. No API key required.
function cartoVoyager(x: number, y: number, z: number, dpr?: number): string {
  const subdomain = "abcd"[(x + y) % 4];
  const retina = dpr && dpr >= 2 ? "@2x" : "";
  return `https://${subdomain}.basemaps.cartocdn.com/rastertiles/voyager/${z}/${x}/${y}${retina}.png`;
}

const ATTRIBUTION = (
  <>
    {"Maps © "}
    <a
      href="https://carto.com/attributions"
      target="_blank"
      rel="noreferrer noopener"
    >
      CARTO
    </a>
    {" · Data © "}
    <a
      href="https://www.openstreetmap.org/copyright"
      target="_blank"
      rel="noreferrer noopener"
    >
      OpenStreetMap
    </a>
  </>
);

function scoreColor(score: number | null): string {
  if (score == null) return "#71717a"; // zinc-500
  if (score >= 8) return "#10b981"; // emerald-500
  if (score >= 6) return "#22c55e"; // green-500
  if (score >= 4) return "#f59e0b"; // amber-500
  return "#ef4444"; // red-500
}

function statusLabel(status: string): string {
  switch (status) {
    case "upcoming":
      return "Not toured";
    case "touring":
      return "Live";
    case "synthesizing":
      return "Generating brief";
    case "completed":
      return "Toured";
    default:
      return status;
  }
}

function kindIcon(kind: SavedLocation["kind"]) {
  const cls = "size-3.5";
  switch (kind) {
    case "work":
      return <Briefcase className={cls} strokeWidth={2.4} />;
    case "school":
      return <GraduationCap className={cls} strokeWidth={2.4} />;
    case "gym":
      return <Dumbbell className={cls} strokeWidth={2.4} />;
    case "family":
      return <Heart className={cls} strokeWidth={2.4} />;
    default:
      return <MapPin className={cls} strokeWidth={2.4} />;
  }
}

function formatCommute(entry: CommuteEntry): string {
  if (entry.minutes != null) {
    const m = Math.round(entry.minutes);
    return `${m} min · ${entry.miles} mi`;
  }
  // Haversine fallback — straight-line, no ETA.
  return `~${entry.miles} mi as the crow flies`;
}

export function HousesMap({
  pins,
  savedLocations,
}: {
  pins: HouseMapPin[];
  savedLocations: SavedLocation[];
}) {
  const [selectedHouse, setSelectedHouse] = useState<string | null>(null);
  const [selectedSaved, setSelectedSaved] = useState<string | null>(null);

  // Center + zoom: include both house pins and saved locations so the
  // initial framing is something useful even if the user's saved
  // locations sit outside the cluster of house markers.
  const allPoints = useMemo(
    () =>
      [
        ...pins.map((p) => ({ lat: p.latitude, lng: p.longitude })),
        ...savedLocations.map((s) => ({ lat: s.lat, lng: s.lng })),
      ],
    [pins, savedLocations],
  );

  const center = useMemo<[number, number]>(() => {
    if (!allPoints.length) return [0, 0];
    return [
      allPoints.reduce((s, p) => s + p.lat, 0) / allPoints.length,
      allPoints.reduce((s, p) => s + p.lng, 0) / allPoints.length,
    ];
  }, [allPoints]);

  const zoom = useMemo(() => {
    if (allPoints.length <= 1) return 13;
    const lats = allPoints.map((p) => p.lat);
    const lngs = allPoints.map((p) => p.lng);
    const span = Math.max(
      Math.max(...lats) - Math.min(...lats),
      Math.max(...lngs) - Math.min(...lngs),
    );
    if (span > 5) return 5;
    if (span > 2) return 7;
    if (span > 0.5) return 9;
    if (span > 0.1) return 11;
    return 13;
  }, [allPoints]);

  const selectedPin = pins.find((p) => p.id === selectedHouse);
  const selectedSavedPin = savedLocations.find((s) => s.id === selectedSaved);
  const savedById = useMemo(() => {
    // Use a plain object — `Map` is shadowed by pigeon-maps' Map import.
    const m: Record<string, SavedLocation> = {};
    for (const s of savedLocations) m[s.id] = s;
    return m;
  }, [savedLocations]);

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
        <Map
          height={Math.min(560, typeof window !== "undefined" ? window.innerHeight - 240 : 480)}
          defaultCenter={center}
          defaultZoom={zoom}
          provider={cartoVoyager}
          attributionPrefix={false}
          attribution={ATTRIBUTION}
        >
          <ZoomControl />

          {/* Saved-location pins: distinct shape (square) and color so
              they don't visually compete with score-colored house pins. */}
          {savedLocations.map((s) => {
            const isSelected = s.id === selectedSaved;
            return (
              <Overlay
                key={`saved-${s.id}`}
                anchor={[s.lat, s.lng]}
                offset={[14, 14]}
              >
                <button
                  type="button"
                  aria-label={s.label}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedHouse(null);
                    setSelectedSaved(isSelected ? null : s.id);
                  }}
                  onTouchEnd={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setSelectedHouse(null);
                    setSelectedSaved(isSelected ? null : s.id);
                  }}
                  className="block rounded-md border-2 border-white dark:border-zinc-100 shadow-md transition-transform active:scale-95 inline-flex items-center justify-center text-white"
                  style={{
                    backgroundColor: "#6366f1", // indigo-500 — clearly distinct from house score colors
                    width: isSelected ? 32 : 26,
                    height: isSelected ? 32 : 26,
                    boxShadow: isSelected
                      ? "0 0 0 3px rgba(99, 102, 241, 0.45)"
                      : "0 1px 3px rgba(0, 0, 0, 0.3)",
                  }}
                >
                  {kindIcon(s.kind)}
                </button>
              </Overlay>
            );
          })}

          {pins.map((p) => {
            const isSelected = p.id === selectedHouse;
            return (
              <Overlay
                key={p.id}
                anchor={[p.latitude, p.longitude]}
                offset={[14, 14]}
              >
                <button
                  type="button"
                  aria-label={p.address}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedSaved(null);
                    setSelectedHouse(isSelected ? null : p.id);
                  }}
                  onTouchEnd={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setSelectedSaved(null);
                    setSelectedHouse(isSelected ? null : p.id);
                  }}
                  className="block rounded-full border-2 border-white dark:border-zinc-100 shadow-md transition-transform active:scale-95"
                  style={{
                    backgroundColor: scoreColor(p.overall_score),
                    width: isSelected ? 36 : 28,
                    height: isSelected ? 36 : 28,
                    boxShadow: isSelected
                      ? "0 0 0 3px rgba(99, 102, 241, 0.5)"
                      : "0 1px 3px rgba(0, 0, 0, 0.3)",
                  }}
                />
              </Overlay>
            );
          })}
        </Map>
      </div>

      {selectedPin ? (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3">
          <div className="flex items-start gap-3">
            {selectedPin.photo_signed_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={selectedPin.photo_signed_url}
                alt={selectedPin.address}
                className="size-14 rounded-md object-cover shrink-0"
              />
            ) : null}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium leading-tight">
                {selectedPin.address}
              </p>
              <p className="text-xs text-zinc-500 mt-0.5">
                {statusLabel(selectedPin.status)}
                {selectedPin.overall_score != null
                  ? ` · score ${selectedPin.overall_score.toFixed(1)}`
                  : ""}
              </p>
              {selectedPin.commute_distances &&
              Object.keys(selectedPin.commute_distances).length > 0 ? (
                <ul className="mt-2 space-y-0.5 text-xs text-zinc-600 dark:text-zinc-400">
                  {Object.entries(selectedPin.commute_distances)
                    .map(([sid, entry]) => ({
                      saved: savedById[sid],
                      entry,
                    }))
                    .filter((row) => row.saved)
                    .sort(
                      (a, b) =>
                        (a.entry.miles ?? Infinity) -
                        (b.entry.miles ?? Infinity),
                    )
                    .map(({ saved, entry }) => (
                      <li key={saved!.id} className="flex items-center gap-1.5">
                        <span className="text-zinc-400 inline-flex">
                          {kindIcon(saved!.kind)}
                        </span>
                        <span>
                          {formatCommute(entry)} from{" "}
                          <span className="text-zinc-700 dark:text-zinc-300">
                            {saved!.label}
                          </span>
                        </span>
                      </li>
                    ))}
                </ul>
              ) : savedLocations.length > 0 ? (
                <p className="text-xs text-zinc-400 mt-2 italic">
                  Computing distances to your saved locations…
                </p>
              ) : null}
              <Link
                href={`/tours/${selectedPin.tour_id}/houses/${selectedPin.id}`}
                className="text-xs text-primary hover:underline mt-2 inline-block"
              >
                Open brief →
              </Link>
            </div>
          </div>
        </div>
      ) : selectedSavedPin ? (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3">
          <div className="flex items-start gap-3">
            <span className="shrink-0 inline-flex items-center justify-center size-9 rounded-md bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400">
              {kindIcon(selectedSavedPin.kind)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium leading-tight">
                {selectedSavedPin.label}
              </p>
              {selectedSavedPin.address ? (
                <p className="text-xs text-zinc-500 mt-0.5">
                  {selectedSavedPin.address}
                </p>
              ) : null}
              <Link
                href="/settings"
                className="text-xs text-primary hover:underline mt-1 inline-block"
              >
                Edit in Settings →
              </Link>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-zinc-500 text-center">
          Tap a marker. Round = house (color = score). Square = your saved
          locations (work, school, etc.). Pin one in Settings.
        </p>
      )}
    </div>
  );
}
