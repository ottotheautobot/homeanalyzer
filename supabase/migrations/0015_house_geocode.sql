-- Geocoding for the map view. Populated lazily on first /map request via
-- Nominatim (OSM); persisted so we don't hammer the API. NULLs are normal
-- for houses whose address didn't resolve — UI just hides them.

alter table public.houses
    add column if not exists latitude double precision;
alter table public.houses
    add column if not exists longitude double precision;
alter table public.houses
    add column if not exists geocoded_at timestamptz;
