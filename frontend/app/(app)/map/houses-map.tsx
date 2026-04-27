"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Map, Overlay, ZoomControl } from "pigeon-maps";

import type { HouseMapPin } from "./page";

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

export function HousesMap({ pins }: { pins: HouseMapPin[] }) {
  const [selected, setSelected] = useState<string | null>(null);

  const center = useMemo<[number, number]>(() => {
    const lats = pins.map((p) => p.latitude);
    const lngs = pins.map((p) => p.longitude);
    return [
      lats.reduce((a, b) => a + b, 0) / lats.length,
      lngs.reduce((a, b) => a + b, 0) / lngs.length,
    ];
  }, [pins]);

  const zoom = useMemo(() => {
    if (pins.length <= 1) return 13;
    const lats = pins.map((p) => p.latitude);
    const lngs = pins.map((p) => p.longitude);
    const span = Math.max(
      Math.max(...lats) - Math.min(...lats),
      Math.max(...lngs) - Math.min(...lngs),
    );
    if (span > 5) return 5;
    if (span > 2) return 7;
    if (span > 0.5) return 9;
    if (span > 0.1) return 11;
    return 13;
  }, [pins]);

  const selectedPin = pins.find((p) => p.id === selected);

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
        <Map
          height={Math.min(560, typeof window !== "undefined" ? window.innerHeight - 240 : 480)}
          defaultCenter={center}
          defaultZoom={zoom}
          attribution={false}
        >
          <ZoomControl />
          {pins.map((p) => {
            const isSelected = p.id === selected;
            // Overlay with an explicit button instead of the default
            // <Marker>: bigger tap target and stopPropagation so the map's
            // pan/drag gesture can't eat the touch event on mobile.
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
                    setSelected(isSelected ? null : p.id);
                  }}
                  onTouchEnd={(e) => {
                    // iOS Safari sometimes misses synthetic clicks after a
                    // brief tap — handle the touch directly. preventDefault
                    // stops the synthesized click from double-firing.
                    e.preventDefault();
                    e.stopPropagation();
                    setSelected(isSelected ? null : p.id);
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
              <Link
                href={`/tours/${selectedPin.tour_id}/houses/${selectedPin.id}`}
                className="text-xs text-primary hover:underline mt-1 inline-block"
              >
                Open brief →
              </Link>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-zinc-500 text-center">
          Tap a marker. Marker color = overall score (red &lt; 4, amber &lt; 6,
          green ≥ 6, emerald ≥ 8).
        </p>
      )}
    </div>
  );
}
