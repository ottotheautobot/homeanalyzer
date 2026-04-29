import type { FloorPlan, FloorPlanRoom } from "@/lib/types";

/** Replaces the SVG visual layout that v1.6 → v2.5 attempted. The
 *  measured-floor-plan pipeline produced unreliable visual output (see
 *  CHANGELOG v2.7), and the schematic-LLM-derived dimensions on their
 *  own are the part that's actually informative. Once we have in-app
 *  capture and can influence camera flow, we'll revisit a real visual
 *  floor plan as a CubiCasa-tier differentiator. */
function approxSqft(room: FloorPlanRoom): number | null {
  if (room.width_ft == null || room.depth_ft == null) return null;
  return Math.round(room.width_ft * room.depth_ft);
}

function roomTotal(rooms: FloorPlanRoom[]): number | null {
  let any = false;
  let total = 0;
  for (const r of rooms) {
    const s = approxSqft(r);
    if (s != null) {
      total += s;
      any = true;
    }
  }
  return any ? total : null;
}

export function FloorPlanView({ plan }: { plan: FloorPlan | null | undefined }) {
  const rooms = plan?.rooms ?? [];
  if (!rooms.length) {
    return (
      <p className="text-sm text-zinc-500">
        No room data extracted from this tour yet.
      </p>
    );
  }

  const total = roomTotal(rooms);

  return (
    <div className="space-y-3">
      {total != null ? (
        <div className="text-xs text-zinc-500">
          ~{total.toLocaleString()} sq ft estimated across {rooms.length} room
          {rooms.length === 1 ? "" : "s"} ·{" "}
          <span className="text-zinc-400">
            dimensions are LLM estimates from the tour transcript
          </span>
        </div>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2">
        {rooms.map((r) => {
          const sqft = approxSqft(r);
          return (
            <div
              key={r.id}
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 p-3"
            >
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-medium text-sm leading-tight capitalize">
                  {r.label}
                </h3>
                {r.width_ft != null && r.depth_ft != null ? (
                  <span className="shrink-0 text-xs tabular-nums text-zinc-600 dark:text-zinc-400">
                    {r.width_ft}&times;{r.depth_ft}&prime;
                    {sqft != null ? (
                      <span className="text-zinc-400">
                        {" "}
                        · {sqft} sq ft
                      </span>
                    ) : null}
                  </span>
                ) : null}
              </div>
              {r.features?.length ? (
                <ul className="mt-2 space-y-1 text-xs text-zinc-600 dark:text-zinc-400">
                  {r.features.map((f, i) => (
                    <li key={i} className="leading-snug">
                      &middot; {f}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
