-- Saved locations + commute caches.
--
-- A "saved location" is a buyer-side anchor like work, kid's school, gym, parents'
-- house. Stored as a JSONB array on the user row so a tour list can render
-- "12 mi from work · 4 mi from school" against every candidate house.
--
-- Each entry in users.saved_locations:
--   { "id": uuid, "label": text, "address": text, "lat": float, "lng": float,
--     "kind": "work" | "school" | "gym" | "family" | "other" }
--
-- Commute distances cache lives on the house so we don't re-hit the routing
-- API on every page render. Shape:
--   houses.commute_distances = {
--     "<saved_location_id>": {
--       "miles": number,
--       "minutes": number | null,    -- null when we fell back to haversine
--       "mode": "driving" | "haversine"
--     }
--   }
-- Cache is invalidated by background recompute when:
--   - saved_locations changes for the owning user (recompute all that user's houses)
--   - a house's geocode (latitude/longitude) changes (recompute that house only)

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS saved_locations jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.houses
  ADD COLUMN IF NOT EXISTS commute_distances jsonb;
