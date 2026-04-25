-- Hours 3–8: Storage bucket + dev-permissive RLS policies.
-- Paste into the Supabase SQL editor and run.
--
-- Why dev policies now: the brief locks Supabase Realtime as the live-update
-- mechanism for observations, and Realtime enforces RLS — without a SELECT
-- policy, authenticated browser clients receive no rows. We add permissive
-- SELECT policies for the `authenticated` role here. INSERT/UPDATE go through
-- the backend (service-role, bypasses RLS), so we add NO write policies.
-- Hours 18–20 replaces these policies with participant-based checks against
-- tour_participants.

-- ---------------------------------------------------------------------------
-- Private Storage bucket for uploaded audio.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('tour-audio', 'tour-audio', false)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Dev-permissive SELECT policies (any authenticated user can read).
-- Tightened in Hours 18–20.
-- ---------------------------------------------------------------------------
create policy "dev: authenticated can read tours"
    on public.tours for select
    to authenticated using (true);

create policy "dev: authenticated can read houses"
    on public.houses for select
    to authenticated using (true);

create policy "dev: authenticated can read observations"
    on public.observations for select
    to authenticated using (true);

create policy "dev: authenticated can read tour_participants"
    on public.tour_participants for select
    to authenticated using (true);
