"use client";

import dagre from "dagre";
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

// 8 distinct room tints walking through the indigo→violet→pink range so tour
// order is visually traceable without being garish.
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

const ROOM_W = 150;
const ROOM_H = 70;
const PADDING = 24;

type Layout = {
  width: number;
  height: number;
  nodes: Array<
    FloorPlanRoom & { x: number; y: number; w: number; h: number; idx: number }
  >;
  edges: Array<{
    fromId: string;
    toId: string;
    points: Array<{ x: number; y: number }>;
  }>;
};

function layoutPlan(plan: FloorPlan): Layout {
  const g = new dagre.graphlib.Graph({ multigraph: false });
  g.setGraph({
    rankdir: "LR",
    nodesep: 28,
    ranksep: 60,
    marginx: PADDING,
    marginy: PADDING,
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const r of plan.rooms) {
    g.setNode(r.id, { width: ROOM_W, height: ROOM_H });
  }
  for (const d of plan.doors) {
    if (g.hasNode(d.from) && g.hasNode(d.to)) {
      g.setEdge(d.from, d.to);
    }
  }

  dagre.layout(g);

  const idx = new Map(plan.rooms.map((r, i) => [r.id, i]));
  const nodes = plan.rooms.map((r) => {
    const n = g.node(r.id);
    return {
      ...r,
      x: n.x - n.width / 2,
      y: n.y - n.height / 2,
      w: n.width,
      h: n.height,
      idx: idx.get(r.id) ?? 0,
    };
  });

  const edges = g.edges().map((e) => {
    const ed = g.edge(e);
    return {
      fromId: e.v,
      toId: e.w,
      points: ed.points as Array<{ x: number; y: number }>,
    };
  });

  const graph = g.graph();
  return {
    width: graph.width ?? 600,
    height: graph.height ?? 400,
    nodes,
    edges,
  };
}

export function FloorPlanView({ plan }: { plan: FloorPlan }) {
  const layout = useMemo(() => layoutPlan(plan), [plan]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (plan.rooms.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        Not enough signal in the tour to reconstruct rooms.
      </p>
    );
  }

  const pill = CONFIDENCE_PILL[plan.confidence];
  const selected = layout.nodes.find((r) => r.id === selectedId);

  function pathFromPoints(points: Array<{ x: number; y: number }>): string {
    if (points.length === 0) return "";
    return points
      .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(" ");
  }

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-amber-200 dark:border-amber-900/50 bg-amber-50/50 dark:bg-amber-950/20 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
        Approximate sketch from the tour video. Not to scale — measurements
        coming in a future version.
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
          aria-label="Floor plan schematic"
        >
          {/* Doorway edges */}
          {layout.edges.map((edge, i) => (
            <path
              key={i}
              d={pathFromPoints(edge.points)}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              className="text-zinc-400 dark:text-zinc-600"
            />
          ))}
          {/* Room rectangles */}
          {layout.nodes.map((node) => {
            const palette = ROOM_PALETTE[node.idx % ROOM_PALETTE.length];
            const isSelected = node.id === selectedId;
            return (
              <g
                key={node.id}
                onClick={() =>
                  setSelectedId(node.id === selectedId ? null : node.id)
                }
                style={{ cursor: "pointer" }}
              >
                <rect
                  x={node.x}
                  y={node.y}
                  width={node.w}
                  height={node.h}
                  rx={12}
                  ry={12}
                  fill={palette.fill}
                  stroke={palette.stroke}
                  strokeWidth={isSelected ? 3 : 2}
                />
                <text
                  x={node.x + node.w / 2}
                  y={node.y + node.h / 2 - 4}
                  textAnchor="middle"
                  fontSize={13}
                  fontWeight={600}
                  fill={palette.text}
                  style={{ textTransform: "capitalize" }}
                >
                  {node.label}
                </text>
                {node.entered_at != null ? (
                  <text
                    x={node.x + node.w / 2}
                    y={node.y + node.h / 2 + 12}
                    textAnchor="middle"
                    fontSize={10}
                    fill={palette.text}
                    opacity={0.7}
                  >
                    {String(node.idx + 1).padStart(2, "0")} ·{" "}
                    {Math.round(node.entered_at)}s
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>

      {selected ? (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3">
          <h3 className="text-sm font-semibold capitalize">
            {selected.label}
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
