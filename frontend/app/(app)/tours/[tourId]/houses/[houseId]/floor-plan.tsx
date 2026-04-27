"use client";

import { useMemo, useState } from "react";

import type { FloorPlan, FloorPlanRoom } from "@/lib/types";

const CONFIDENCE_PILL: Record<
  FloorPlan["confidence"],
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

const PX_PER_FT = 7;
const PADDING = 16;
const FALLBACK_W = 12;
const FALLBACK_D = 12;

type Dir = "E" | "S" | "W" | "N";
const DIR_VEC: Record<Dir, [number, number]> = {
  E: [1, 0],
  S: [0, 1],
  W: [-1, 0],
  N: [0, -1],
};

type Placement = {
  cellX: number;
  cellY: number;
  pxX: number;
  pxY: number;
  w: number;
  h: number;
  idx: number;
} & FloorPlanRoom;

type Layout = {
  rooms: Placement[];
  doors: Array<{
    fromId: string;
    toId: string;
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  }>;
  width: number;
  height: number;
};

/**
 * Two-pass: greedy grid placement (which cell each room is in), then size
 * each cell to the largest room in its row (height) and column (width). This
 * lets rooms have honest-ish dimensions while still tiling cleanly so it
 * reads as a floor plan instead of a flowchart.
 */
function placeRooms(plan: FloorPlan): Layout {
  if (plan.rooms.length === 0) {
    return { rooms: [], doors: [], width: 0, height: 0 };
  }

  const adj = new Map<string, Set<string>>();
  for (const r of plan.rooms) adj.set(r.id, new Set());
  for (const d of plan.doors) {
    adj.get(d.from)?.add(d.to);
    adj.get(d.to)?.add(d.from);
  }

  const cellOf = new Map<string, [number, number]>();
  const cellsTaken = new Map<string, string>();
  function place(roomId: string, x: number, y: number) {
    cellOf.set(roomId, [x, y]);
    cellsTaken.set(`${x},${y}`, roomId);
  }
  function isFree(x: number, y: number) {
    return !cellsTaken.has(`${x},${y}`);
  }

  place(plan.rooms[0].id, 0, 0);

  for (let i = 1; i < plan.rooms.length; i++) {
    const room = plan.rooms[i];
    const placedNeighbors = Array.from(adj.get(room.id) ?? []).filter((id) =>
      cellOf.has(id),
    );
    const anchor =
      placedNeighbors[0] ??
      Array.from(cellOf.keys()).find((id) => id === plan.rooms[i - 1].id) ??
      plan.rooms[i - 1].id;

    let placedRoom = false;
    for (const tryAnchor of [
      anchor,
      ...placedNeighbors.filter((id) => id !== anchor),
    ]) {
      const [ax, ay] = cellOf.get(tryAnchor)!;
      for (const dir of ["E", "S", "W", "N"] as Dir[]) {
        const [dx, dy] = DIR_VEC[dir];
        if (isFree(ax + dx, ay + dy)) {
          place(room.id, ax + dx, ay + dy);
          placedRoom = true;
          break;
        }
      }
      if (placedRoom) break;
    }

    if (!placedRoom) {
      const [ax, ay] = cellOf.get(plan.rooms[i - 1].id)!;
      let radius = 1;
      while (!placedRoom && radius < 50) {
        for (let dx = -radius; dx <= radius && !placedRoom; dx++) {
          for (let dy = -radius; dy <= radius && !placedRoom; dy++) {
            if (Math.abs(dx) !== radius && Math.abs(dy) !== radius) continue;
            if (isFree(ax + dx, ay + dy)) {
              place(room.id, ax + dx, ay + dy);
              placedRoom = true;
            }
          }
        }
        radius++;
      }
    }
  }

  const cells = Array.from(cellOf.values());
  const minX = Math.min(...cells.map(([x]) => x));
  const minY = Math.min(...cells.map(([, y]) => y));
  const maxX = Math.max(...cells.map(([x]) => x));
  const maxY = Math.max(...cells.map(([, y]) => y));

  // Per-row max depth and per-col max width. This is the trick that makes
  // rooms tile: every room in a row gets the row's height, every room in a
  // column gets the column's width. Some rooms get visually scaled up from
  // their estimate, but adjacency walls share cleanly.
  const colWidthFt = new Map<number, number>();
  const rowHeightFt = new Map<number, number>();
  for (const [id, [cx, cy]] of cellOf.entries()) {
    const room = plan.rooms.find((r) => r.id === id)!;
    const w = room.width_ft ?? FALLBACK_W;
    const d = room.depth_ft ?? FALLBACK_D;
    colWidthFt.set(cx, Math.max(colWidthFt.get(cx) ?? 0, w));
    rowHeightFt.set(cy, Math.max(rowHeightFt.get(cy) ?? 0, d));
  }

  // Cumulative pixel offsets per col/row.
  const colOffsetPx = new Map<number, number>();
  let cum = PADDING;
  for (let cx = minX; cx <= maxX; cx++) {
    colOffsetPx.set(cx, cum);
    cum += (colWidthFt.get(cx) ?? FALLBACK_W) * PX_PER_FT;
  }
  const totalW = cum + PADDING;

  const rowOffsetPx = new Map<number, number>();
  cum = PADDING;
  for (let cy = minY; cy <= maxY; cy++) {
    rowOffsetPx.set(cy, cum);
    cum += (rowHeightFt.get(cy) ?? FALLBACK_D) * PX_PER_FT;
  }
  const totalH = cum + PADDING;

  const idxById = new Map(plan.rooms.map((r, i) => [r.id, i]));
  const placements: Placement[] = plan.rooms.map((r) => {
    const [cx, cy] = cellOf.get(r.id)!;
    const wFt = colWidthFt.get(cx) ?? FALLBACK_W;
    const hFt = rowHeightFt.get(cy) ?? FALLBACK_D;
    return {
      ...r,
      cellX: cx - minX,
      cellY: cy - minY,
      pxX: colOffsetPx.get(cx)!,
      pxY: rowOffsetPx.get(cy)!,
      w: wFt * PX_PER_FT,
      h: hFt * PX_PER_FT,
      idx: idxById.get(r.id) ?? 0,
    };
  });

  const placementById = new Map(placements.map((p) => [p.id, p]));
  const doors: Layout["doors"] = [];
  const seen = new Set<string>();
  for (const d of plan.doors) {
    const a = placementById.get(d.from);
    const b = placementById.get(d.to);
    if (!a || !b) continue;
    const key = [d.from, d.to].sort().join("|");
    if (seen.has(key)) continue;
    seen.add(key);

    const dx = b.cellX - a.cellX;
    const dy = b.cellY - a.cellY;
    if (Math.abs(dx) + Math.abs(dy) !== 1) continue;

    if (dx === 1) {
      const x = a.pxX + a.w;
      const yMid = a.pxY + a.h / 2;
      doors.push({ fromId: d.from, toId: d.to, x1: x, y1: yMid - 12, x2: x, y2: yMid + 12 });
    } else if (dx === -1) {
      const x = a.pxX;
      const yMid = a.pxY + a.h / 2;
      doors.push({ fromId: d.from, toId: d.to, x1: x, y1: yMid - 12, x2: x, y2: yMid + 12 });
    } else if (dy === 1) {
      const y = a.pxY + a.h;
      const xMid = a.pxX + a.w / 2;
      doors.push({ fromId: d.from, toId: d.to, x1: xMid - 14, y1: y, x2: xMid + 14, y2: y });
    } else {
      const y = a.pxY;
      const xMid = a.pxX + a.w / 2;
      doors.push({ fromId: d.from, toId: d.to, x1: xMid - 14, y1: y, x2: xMid + 14, y2: y });
    }
  }

  return { rooms: placements, doors, width: totalW, height: totalH };
}

export function FloorPlanView({ plan }: { plan: FloorPlan }) {
  const layout = useMemo(() => placeRooms(plan), [plan]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (plan.rooms.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        Not enough signal in the tour to reconstruct rooms.
      </p>
    );
  }

  const pill = CONFIDENCE_PILL[plan.confidence];
  const selected = layout.rooms.find((r) => r.id === selectedId);

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-amber-200 dark:border-amber-900/50 bg-amber-50/50 dark:bg-amber-950/20 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
        Rough estimate, not a measured plan. Room sizes are guessed from the
        transcript — treat with skepticism.
      </div>

      <div className="flex items-center gap-2 text-xs">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-md font-medium ${pill.cls}`}
        >
          {pill.label}
        </span>
        {plan.notes ? (
          <span className="text-zinc-500">{plan.notes}</span>
        ) : null}
      </div>

      <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 overflow-x-auto">
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width="100%"
          style={{ minWidth: layout.width, height: "auto" }}
          className="block"
          role="img"
          aria-label="Estimated floor plan schematic"
        >
          {layout.rooms.map((room) => {
            const palette = ROOM_PALETTE[room.idx % ROOM_PALETTE.length];
            const isSelected = room.id === selectedId;
            const dim =
              room.width_ft && room.depth_ft
                ? `≈${room.width_ft}×${room.depth_ft}′`
                : null;
            return (
              <g
                key={room.id}
                onClick={() =>
                  setSelectedId(room.id === selectedId ? null : room.id)
                }
                style={{ cursor: "pointer" }}
              >
                <rect
                  x={room.pxX}
                  y={room.pxY}
                  width={room.w}
                  height={room.h}
                  fill={palette.fill}
                  stroke={palette.stroke}
                  strokeWidth={isSelected ? 3 : 2}
                />
                <text
                  x={room.pxX + room.w / 2}
                  y={room.pxY + room.h / 2 - 6}
                  textAnchor="middle"
                  fontSize={13}
                  fontWeight={600}
                  fill={palette.text}
                  style={{ textTransform: "capitalize" }}
                >
                  {room.label}
                </text>
                {dim ? (
                  <text
                    x={room.pxX + room.w / 2}
                    y={room.pxY + room.h / 2 + 10}
                    textAnchor="middle"
                    fontSize={11}
                    fill={palette.text}
                    opacity={0.8}
                  >
                    {dim}
                  </text>
                ) : null}
              </g>
            );
          })}
          {layout.doors.map((door, i) => (
            <line
              key={i}
              x1={door.x1}
              y1={door.y1}
              x2={door.x2}
              y2={door.y2}
              stroke="#fafafa"
              strokeWidth={5}
              strokeLinecap="round"
            />
          ))}
        </svg>
      </div>

      {selected ? (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3">
          <h3 className="text-sm font-semibold capitalize">
            {selected.label}
            {selected.width_ft && selected.depth_ft ? (
              <span className="ml-2 text-xs text-zinc-500 font-normal">
                ≈ {selected.width_ft}×{selected.depth_ft} ft (estimate)
              </span>
            ) : null}
          </h3>
          {selected.features.length > 0 ? (
            <ul className="mt-1.5 ml-4 list-disc space-y-0.5 text-sm text-zinc-700 dark:text-zinc-300">
              {selected.features.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-zinc-500">No features captured.</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-zinc-500 text-center">
          Tap a room to see its features.
        </p>
      )}
    </div>
  );
}
