import type {
  FloorPlan,
  FloorPlanDoor,
  FloorPlanRoom,
  MeasuredFloorPlan,
  MeasuredFloorPlanRoom,
} from "@/lib/types";

const M_TO_FT = 3.28084;

/** Per-room source provenance, surfaced to the renderer so the UI can
 *  visually distinguish "verified by both", "estimated only", and
 *  "vision saw but transcript missed". Carried as a normal field on
 *  the room dict. */
export type RoomSource = "verified" | "estimate" | "vision-only";

export type MergedFloorPlanRoom = FloorPlanRoom & {
  /** "verified" — matched in both schematic and measured.
   *  "estimate" — schematic only (transcript said it; camera didn't see it).
   *  "vision-only" — measured only (camera saw it; transcript missed it). */
  source: RoomSource;
};

export type MergedFloorPlan = Omit<FloorPlan, "rooms"> & {
  rooms: MergedFloorPlanRoom[];
};

function labelKey(label: string | null | undefined): string {
  return (label || "").toLowerCase().trim();
}

/**
 * Cohesive union of the two data sources into one floor plan.
 *
 * The schematic (LLM-extracted from the transcript) and the measured
 * plan (from the MASt3R/VGGT pipeline) each catch what the other
 * misses:
 *   - Schematic has a fuller room list (the agent talks about the
 *     upstairs office even if the camera never went there).
 *   - Measured has real dimensions + real adjacency from where the
 *     camera actually moved.
 *
 * This merge is a true union, not a replacement:
 *   1. The schematic's room list is canonical "what rooms exist".
 *   2. For each schematic room with a matching measured room (by
 *      label, case-insensitive), we use the measured w/d in feet
 *      and tag it `source: "verified"`. No match → keep the LLM
 *      estimate, tag `source: "estimate"`.
 *   3. Measured rooms that didn't match any schematic room get
 *      appended with `source: "vision-only"` — the camera saw a
 *      room the transcript didn't name.
 *   4. Doors from both sources are unioned, deduped on the (from,to)
 *      sorted pair. Measured doors get IDs remapped to the schematic
 *      room IDs they correspond to so the merged adjacency graph is
 *      internally consistent.
 *   5. `features` (transcript-derived per-room bullets like "tile
 *      floor", "south-facing window") are always carried from the
 *      schematic — measured data has no such concept.
 */
export function mergeFloorPlans(
  measured: MeasuredFloorPlan | null,
  schematic: FloorPlan | null,
): MergedFloorPlan | null {
  if (!measured && !schematic) return null;

  // No measured data → return schematic as-is, all rooms tagged "estimate".
  if (!measured || !measured.rooms?.length) {
    if (!schematic) return null;
    return {
      ...schematic,
      rooms: schematic.rooms.map((r) => ({ ...r, source: "estimate" })),
    };
  }

  // No schematic → return measured as-is, all rooms tagged "vision-only".
  if (!schematic || !schematic.rooms?.length) {
    return {
      rooms: measured.rooms.map((mr) => ({
        id: mr.id,
        label: mr.label || "Room",
        entered_at: null,
        exited_at: null,
        features: [],
        width_ft: Math.max(1, Math.round(mr.width_m * M_TO_FT)),
        depth_ft: Math.max(1, Math.round(mr.depth_m * M_TO_FT)),
        source: "vision-only",
      })),
      doors: measured.doors.map((d) => ({
        from: d.from,
        to: d.to,
        via: "transcript",
      })),
      confidence: measured.confidence,
      notes: measured.notes,
      model_version: measured.model_version,
    };
  }

  // Both sources present — union them.
  const measuredByLabel = new Map<string, MeasuredFloorPlanRoom>();
  for (const mr of measured.rooms) {
    const key = labelKey(mr.label);
    if (key && !measuredByLabel.has(key)) {
      measuredByLabel.set(key, mr);
    }
  }

  // measured.id → schematic.id mapping, for door remapping later.
  const measuredToSchematicId = new Map<string, string>();

  const rooms: MergedFloorPlanRoom[] = [];
  const usedMeasuredIds = new Set<string>();

  // Pass 1: schematic rooms. Override dimensions when matched.
  for (const sr of schematic.rooms) {
    const match = measuredByLabel.get(labelKey(sr.label));
    if (match && !usedMeasuredIds.has(match.id)) {
      usedMeasuredIds.add(match.id);
      measuredToSchematicId.set(match.id, sr.id);
      rooms.push({
        ...sr,
        // Real dimensions from measurement override LLM estimate.
        width_ft: Math.max(1, Math.round(match.width_m * M_TO_FT)),
        depth_ft: Math.max(1, Math.round(match.depth_m * M_TO_FT)),
        source: "verified",
      });
    } else {
      rooms.push({ ...sr, source: "estimate" });
    }
  }

  // Pass 2: measured rooms that didn't match any schematic room.
  for (const mr of measured.rooms) {
    if (usedMeasuredIds.has(mr.id)) continue;
    rooms.push({
      id: mr.id,
      label: mr.label || "Room",
      entered_at: null,
      exited_at: null,
      features: [],
      width_ft: Math.max(1, Math.round(mr.width_m * M_TO_FT)),
      depth_ft: Math.max(1, Math.round(mr.depth_m * M_TO_FT)),
      source: "vision-only",
    });
  }

  // Doors: schematic + measured (with id-remap), deduped on sorted pair.
  const dedupKey = (a: string, b: string) =>
    a < b ? `${a}|${b}` : `${b}|${a}`;
  const seen = new Set<string>();
  const doors: FloorPlanDoor[] = [];
  for (const sd of schematic.doors) {
    const key = dedupKey(sd.from, sd.to);
    if (seen.has(key)) continue;
    seen.add(key);
    doors.push(sd);
  }
  for (const md of measured.doors) {
    const from = measuredToSchematicId.get(md.from) ?? md.from;
    const to = measuredToSchematicId.get(md.to) ?? md.to;
    const key = dedupKey(from, to);
    if (seen.has(key)) continue;
    seen.add(key);
    doors.push({ from, to, via: "transcript" });
  }

  return {
    rooms,
    doors,
    confidence: measured.confidence,
    notes:
      measured.notes ??
      schematic.notes ??
      "Combined transcript layout + measured dimensions.",
    model_version: measured.model_version,
  };
}

/**
 * Backwards-compatible wrapper for the old name. Always returns a plan
 * shape; callers expect non-null when the inputs are valid.
 *
 * @deprecated Prefer `mergeFloorPlans` which is more explicit about
 *   handling missing sources.
 */
export function mergeMeasuredIntoSchematic(
  measured: MeasuredFloorPlan,
  schematic: FloorPlan | null,
): FloorPlan {
  const merged = mergeFloorPlans(measured, schematic);
  if (!merged) {
    return {
      rooms: [],
      doors: [],
      confidence: "low",
      notes: null,
      model_version: "empty",
    };
  }
  // Strip `source` from rooms for callers expecting the bare FloorPlan shape.
  return {
    ...merged,
    rooms: merged.rooms.map((r) => {
      const { source: _source, ...rest } = r;
      return rest;
    }),
  };
}
