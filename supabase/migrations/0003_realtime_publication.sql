-- Hours 3–8: Add observations + houses to the supabase_realtime publication.
--
-- The dev SELECT policy in 0002 lets authenticated clients receive Realtime
-- payloads, but Realtime only broadcasts changes for tables that are members
-- of the `supabase_realtime` publication. Without this, postgres_changes
-- subscriptions connect successfully but never fire.
--
-- Wrapped in DO blocks so re-running the migration is safe — Supabase Studio's
-- "Realtime" toggle may have already added a table to the publication, and
-- `alter publication ... add table` raises 42710 in that case.

do $$ begin
  alter publication supabase_realtime add table public.observations;
exception when duplicate_object then null;
end $$;

do $$ begin
  alter publication supabase_realtime add table public.houses;
exception when duplicate_object then null;
end $$;
