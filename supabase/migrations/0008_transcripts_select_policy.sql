-- Realtime enforces RLS. transcripts has RLS enabled (0001) but 0002 forgot
-- to add a SELECT policy for it, so authenticated clients subscribing to
-- realtime postgres_changes on transcripts get no rows even when the table
-- is in the supabase_realtime publication. Mirror the dev-permissive policy
-- pattern used in 0002 for observations/houses/tours.
--
-- Tightened in Hours 18–20 polish phase along with the others.

create policy "dev: authenticated can read transcripts"
    on public.transcripts for select
    to authenticated using (true);
