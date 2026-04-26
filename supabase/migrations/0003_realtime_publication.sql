-- Hours 3–8: Add observations to the supabase_realtime publication.
--
-- The dev SELECT policy in 0002 lets authenticated clients receive Realtime
-- payloads, but Realtime only broadcasts changes for tables that are members
-- of the `supabase_realtime` publication. Without this, postgres_changes
-- subscriptions on `observations` connect successfully but never fire.
--
-- The Supabase dashboard's "Realtime" toggle on a table runs this same
-- statement under the hood; we put it in a migration so the setup is
-- reproducible across environments.

alter publication supabase_realtime add table public.observations;
alter publication supabase_realtime add table public.houses;
