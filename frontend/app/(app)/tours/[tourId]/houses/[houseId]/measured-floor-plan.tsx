"use client";

import { Loader2, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { clientFetch } from "@/lib/api-client";
import type {
  House,
  MeasuredFloorPlan,
  MeasuredFloorPlanRoom,
} from "@/lib/types";

const ROOM_PALETTE = [
  { fill: "#eef2ff", stroke: "#6366f1", text: "#312e81" },
  { fill: "#ede9fe", stroke: "#8b5cf6", text: "#4c1d95" },
  { fill: "#fae8ff", stroke: "#a855f7", text: "#581c87" },
  { fill: "#fdf4ff", stroke: "#d946ef", text: "#701a75" },
  { fill: "#fce7f3", stroke: "#ec4899", text: "#831843" },
  { fill: "#ffe4e6", stroke: "#f43f5e", text: "#881337" },
  { fill: "#ecfeff", stroke: "#06b6d4", text: "#164e63" },
  { fill: "#dcfce7", stroke: "#22c55e", text: "#14532d" },
];

const PX_PER_METER = 28; // ~8.5 px/ft, comfortable on phone
const PADDING = 20;

const CONFIDENCE_PILL: Record<
  MeasuredFloorPlan["confidence"],
  { label: string; cls: string }
> = {
  low: {
    label: "Low confidence",
    cls: "bg-zinc-100 dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400",
  },
  medium: {
    label: "Medium confidence",
    cls: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
  },
  high: {
    label: "High confidence",
    cls: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400",
  },
};

function metersToFeet(m: number): number {
  return m * 3.28084;
}

function bbox(rooms: MeasuredFloorPlanRoom[]): [number, number, number, number] {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of rooms) {
    for (const [x, y] of r.polygon_m) {
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  if (!isFinite(minX)) return [0, 0, 0, 0];
  return [minX, minY, maxX, maxY];
}

export function MeasuredFloorPlanView({ plan }: { plan: MeasuredFloorPlan }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const layout = useMemo(() => {
    const [minX, minY, maxX, maxY] = bbox(plan.rooms);
    const width = (maxX - minX) * PX_PER_METER + PADDING * 2;
    const height = (maxY - minY) * PX_PER_METER + PADDING * 2;
    const transform = (x: number, y: number) => [
      (x - minX) * PX_PER_METER + PADDING,
      (y - minY) * PX_PER_METER + PADDING,
    ];
    return { width, height, transform };
  }, [plan.rooms]);

  const selected = plan.rooms.find((r) => r.id === selectedId);

  if (plan.rooms.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        Reconstruction produced no rooms. {plan.notes ?? ""}
      </p>
    );
  }

  const pill = CONFIDENCE_PILL[plan.confidence];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-md font-medium ${pill.cls}`}
        >
          {pill.label}
        </span>
        <span className="text-zinc-500">
          Reconstructed from tour video ({plan.model_version})
        </span>
      </div>
      {plan.notes ? (
        <p className="text-xs text-zinc-500">{plan.notes}</p>
      ) : null}

      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 overflow-x-auto">
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width="100%"
          style={{ minWidth: layout.width, height: "auto" }}
          className="block"
          role="img"
          aria-label="Measured floor plan"
        >
          {plan.rooms.map((room, idx) => {
            const palette = ROOM_PALETTE[idx % ROOM_PALETTE.length];
            const isSelected = room.id === selectedId;
            const points = room.polygon_m
              .map(([x, y]) => layout.transform(x, y).join(","))
              .join(" ");
            // Centroid for label.
            let cx = 0;
            let cy = 0;
            for (const [x, y] of room.polygon_m) {
              const [px, py] = layout.transform(x, y);
              cx += px;
              cy += py;
            }
            cx /= room.polygon_m.length;
            cy /= room.polygon_m.length;
            // Per-room confidence drives visual treatment so user knows
            // which dimensions to trust at a glance.
            const lowConf = room.confidence < 0.5;
            return (
              <g
                key={room.id}
                onClick={() =>
                  setSelectedId(room.id === selectedId ? null : room.id)
                }
                style={{ cursor: "pointer" }}
              >
                <polygon
                  points={points}
                  fill={palette.fill}
                  fillOpacity={lowConf ? 0.4 : 1}
                  stroke={palette.stroke}
                  strokeWidth={isSelected ? 3 : 2}
                  strokeLinejoin="round"
                  strokeDasharray={lowConf ? "6 4" : undefined}
                />
                <text
                  x={cx}
                  y={cy - 6}
                  textAnchor="middle"
                  fontSize={13}
                  fontWeight={600}
                  fill={palette.text}
                  style={{ textTransform: "capitalize" }}
                  opacity={lowConf ? 0.6 : 1}
                >
                  {room.label}
                </text>
                <text
                  x={cx}
                  y={cy + 10}
                  textAnchor="middle"
                  fontSize={10}
                  fill={palette.text}
                  opacity={lowConf ? 0.45 : 0.75}
                >
                  {metersToFeet(room.width_m).toFixed(0)}×
                  {metersToFeet(room.depth_m).toFixed(0)} ft
                  {lowConf ? " ?" : ""}
                </text>
              </g>
            );
          })}
          {plan.doors.map((door, i) => {
            const [px, py] = layout.transform(door.x_m, door.z_m);
            return (
              <circle
                key={i}
                cx={px}
                cy={py}
                r={4}
                fill="#fafafa"
                stroke="#71717a"
                strokeWidth={1}
              />
            );
          })}
        </svg>
      </div>

      {selected ? (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3 space-y-1.5">
          <h3 className="text-sm font-semibold capitalize">
            {selected.label}{" "}
            <span className="ml-2 text-xs text-zinc-500 font-normal">
              {metersToFeet(selected.width_m).toFixed(1)}×
              {metersToFeet(selected.depth_m).toFixed(1)} ft (
              {selected.width_m.toFixed(1)}×{selected.depth_m.toFixed(1)} m)
            </span>
          </h3>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
            <span>
              Confidence{" "}
              <span
                className={
                  selected.confidence >= 0.7
                    ? "text-emerald-600 dark:text-emerald-400"
                    : selected.confidence >= 0.5
                      ? "text-amber-600 dark:text-amber-400"
                      : "text-zinc-500"
                }
              >
                {(selected.confidence * 100).toFixed(0)}%
              </span>
            </span>
            {typeof selected.sample_count === "number" ? (
              <span>{selected.sample_count} frames</span>
            ) : null}
            {selected.source === "camera-path" ? (
              <span className="text-amber-600 dark:text-amber-400">
                Rough estimate (sparse coverage)
              </span>
            ) : selected.source === "wall-points" ? (
              <span>Wall-point bbox</span>
            ) : null}
          </div>
        </div>
      ) : (
        <p className="text-xs text-zinc-500 text-center">
          Tap a room to see measurements. Dashed outlines = rough estimates.
        </p>
      )}
    </div>
  );
}

/**
 * Loading + control panel: shown when measurement is pending or hasn't run.
 * Posts to /houses/{id}/measure-floorplan on click.
 */
export function MeasuredFloorPlanControls({
  house,
}: {
  house: House;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: async (): Promise<House> =>
      clientFetch<House>(`/houses/${house.id}/measure-floorplan`, {
        method: "POST",
      }),
    onSuccess: () => {
      setError(null);
      router.refresh();
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Failed");
    },
  });

  const cancel = useMutation({
    mutationFn: async (): Promise<House> =>
      clientFetch<House>(`/houses/${house.id}/measure-floorplan`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setError(null);
      router.refresh();
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Failed");
    },
  });

  const status = house.measured_floor_plan_status;
  const isPending = status === "pending" || start.isPending;
  const hasFailed = status === "failed";
  const startedAt = house.measured_floor_plan_started_at
    ? new Date(house.measured_floor_plan_started_at)
    : null;
  // 20+ min in pending = the worker thread almost certainly died. Surface
  // an unstick affordance instead of leaving the user staring at a spinner.
  const stalePending =
    status === "pending" &&
    startedAt !== null &&
    Date.now() - startedAt.getTime() > 20 * 60 * 1000;

  return (
    <div className="space-y-2">
      {isPending ? (
        <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 p-3 space-y-2">
          <div className="flex items-center gap-3">
            <Loader2 className="size-4 animate-spin text-primary shrink-0" />
            <div className="text-sm min-w-0 flex-1">
              <div className="font-medium">
                {stalePending ? "Measurement seems stuck" : "Measuring layout from video…"}
              </div>
              <div className="text-xs text-zinc-500">
                {stalePending
                  ? "Started over 20 minutes ago — the GPU job most likely died on a worker restart."
                  : "Reconstructing camera path and room geometry on a GPU. Usually 5–15 minutes."}
                {startedAt
                  ? ` Started ${startedAt.toLocaleTimeString()}.`
                  : ""}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 pl-7">
            <Button
              onClick={() => start.mutate()}
              disabled={start.isPending || cancel.isPending}
              size="sm"
              variant="secondary"
            >
              <RefreshCcw className="size-3.5 mr-1.5" />
              Retry
            </Button>
            <Button
              onClick={() => cancel.mutate()}
              disabled={start.isPending || cancel.isPending}
              size="sm"
              variant="ghost"
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button
          onClick={() => start.mutate()}
          disabled={isPending}
          variant="secondary"
          size="sm"
        >
          <RefreshCcw className="size-3.5 mr-1.5" />
          {hasFailed ? "Retry measurement" : "Measure layout (beta)"}
        </Button>
      )}
      {hasFailed && house.measured_floor_plan_error ? (
        <p className="text-xs text-red-600 dark:text-red-400">
          {house.measured_floor_plan_error}
        </p>
      ) : null}
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}
