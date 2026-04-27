import type { FloorPlan } from "@/lib/types";

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

export function FloorPlanView({ plan }: { plan: FloorPlan }) {
  const labelById = new Map(plan.rooms.map((r) => [r.id, r.label]));

  // Group adjacencies by room for the per-card "connects to" line.
  const neighborsByRoom = new Map<string, string[]>();
  for (const door of plan.doors) {
    const a = labelById.get(door.from);
    const b = labelById.get(door.to);
    if (!a || !b) continue;
    if (!neighborsByRoom.has(door.from)) neighborsByRoom.set(door.from, []);
    if (!neighborsByRoom.has(door.to)) neighborsByRoom.set(door.to, []);
    neighborsByRoom.get(door.from)!.push(b);
    neighborsByRoom.get(door.to)!.push(a);
  }

  if (plan.rooms.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        Not enough signal in the tour to reconstruct rooms.
      </p>
    );
  }

  const pill = CONFIDENCE_PILL[plan.confidence];

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

      <ol className="space-y-2">
        {plan.rooms.map((room, idx) => {
          const neighbors = Array.from(
            new Set(neighborsByRoom.get(room.id) || []),
          ).filter((n) => n !== room.label);
          return (
            <li
              key={room.id}
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3"
            >
              <div className="flex items-baseline gap-2">
                <span className="text-xs tabular-nums text-zinc-400">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <h3 className="text-sm font-semibold capitalize">
                  {room.label}
                </h3>
                {room.entered_at != null ? (
                  <span className="text-xs text-zinc-500 tabular-nums">
                    @{Math.round(room.entered_at)}s
                  </span>
                ) : null}
              </div>
              {room.features.length > 0 ? (
                <ul className="mt-1.5 ml-6 list-disc space-y-0.5 text-sm text-zinc-700 dark:text-zinc-300">
                  {room.features.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              ) : null}
              {neighbors.length > 0 ? (
                <p className="mt-2 ml-6 text-xs text-zinc-500">
                  <span className="font-medium text-zinc-600 dark:text-zinc-400">
                    Connects to:
                  </span>{" "}
                  <span className="capitalize">{neighbors.join(", ")}</span>
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
