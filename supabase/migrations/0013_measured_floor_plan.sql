-- Measured floor plan reconstructed from the tour video via Modal+SLAM.
-- Stored alongside the existing schematic floor_plan_json so both can
-- coexist; the UI prefers measured when available, falls back to schematic.
--
-- Status column tracks the long-running reconstruction job:
--   null/idle -> never run
--   pending   -> Modal job dispatched, waiting on result
--   ready     -> reconstruction complete, polygons in measured_floor_plan_json
--   failed    -> reconstruction errored; see measured_floor_plan_error

alter table public.houses
    add column if not exists measured_floor_plan_json jsonb;
alter table public.houses
    add column if not exists measured_floor_plan_status text
    check (measured_floor_plan_status in ('pending', 'ready', 'failed'));
alter table public.houses
    add column if not exists measured_floor_plan_error text;
alter table public.houses
    add column if not exists measured_floor_plan_started_at timestamptz;
