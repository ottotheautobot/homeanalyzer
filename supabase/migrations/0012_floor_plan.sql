-- Floor plan schematic: lo-fi room+adjacency graph derived from observations
-- and transcript by Sonnet. Stored denormalized so regeneration is a single
-- column update.

alter table public.houses
    add column if not exists floor_plan_json jsonb;
