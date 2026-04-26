-- Hours 8-14 follow-up: per-user default Zoom URL.
-- A v2 settings page will let users edit this in-app; for now it's set via SQL.

alter table public.users
    add column if not exists default_zoom_url text;
