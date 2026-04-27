import type {
  FloorPlan,
  FloorPlanDoor,
  FloorPlanRoom,
  MeasuredFloorPlan,
} from "@/lib/types";

const M_TO_FT = 3.28084;

/**
 * Convert a measured floor plan + (optional) schematic into the schematic
 * `FloorPlan` shape so a single renderer can show one unified view:
 *   - Rectangle layout from schematic-style greedy grid placement
 *   - Real measured dimensions (m → ft) instead of LLM estimates
 *   - Adjacency from measured doors so room placement reflects actual
 *     spatial relationships, not transcript-inferred sequence
 *   - Per-room `features` carried over from the schematic (transcript-
 *     derived bullets like "tile floor" — useful per-room detail that
 *     measured data alone doesn't produce)
 */
export function mergeMeasuredIntoSchematic(
  measured: MeasuredFloorPlan,
  schematic: FloorPlan | null,
): FloorPlan {
  const schematicByLabel = new Map<string, FloorPlanRoom>();
  if (schematic) {
    for (const r of schematic.rooms) {
      const key = (r.label || "").toLowerCase().trim();
      if (key && !schematicByLabel.has(key)) {
        schematicByLabel.set(key, r);
      }
    }
  }

  const rooms: FloorPlanRoom[] = measured.rooms.map((mr) => {
    const labelKey = (mr.label || "").toLowerCase().trim();
    const matchedSchematic = schematicByLabel.get(labelKey);
    return {
      id: mr.id,
      label: mr.label || matchedSchematic?.label || "Room",
      entered_at: matchedSchematic?.entered_at ?? null,
      exited_at: matchedSchematic?.exited_at ?? null,
      features: matchedSchematic?.features ?? [],
      width_ft: Math.max(1, Math.round(mr.width_m * M_TO_FT)),
      depth_ft: Math.max(1, Math.round(mr.depth_m * M_TO_FT)),
    };
  });

  const doors: FloorPlanDoor[] = measured.doors.map((d) => ({
    from: d.from,
    to: d.to,
    via: "transcript",
  }));

  return {
    rooms,
    doors,
    confidence: measured.confidence,
    notes: measured.notes,
    model_version: measured.model_version,
  };
}
