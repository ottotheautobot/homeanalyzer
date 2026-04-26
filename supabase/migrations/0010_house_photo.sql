-- Curb appeal photo for the house. Stored in the same tour-audio bucket
-- under the house's prefix so the existing per-house storage cleanup
-- picks it up on delete.

alter table public.houses
    add column if not exists photo_url text;
