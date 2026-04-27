-- Per-tour shareable read-only links. The owner mints a random token; anyone
-- with the URL can fetch the tour + its houses (no auth) until the owner
-- revokes it. Backend reads share_token via service-role; we never expose
-- this column over RLS.

alter table public.tours
    add column if not exists share_token text;
alter table public.tours
    add column if not exists shared_at timestamptz;

create unique index if not exists tours_share_token_uniq
    on public.tours(share_token)
    where share_token is not null;
