-- House Tour Notes — initial schema
-- Single-file migration. Paste into Supabase SQL editor and run.
-- Matches PROJECT_BRIEF.md "Data model" section exactly.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
create table public.users (
    id uuid primary key default gen_random_uuid(),
    email text not null unique,
    name text,
    role text check (role in ('buyer', 'partner', 'agent'))
);

-- ---------------------------------------------------------------------------
-- tours
-- ---------------------------------------------------------------------------
create table public.tours (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references public.users(id) on delete cascade,
    name text not null,
    location text,
    zoom_pmr_url text,
    created_at timestamptz not null default now(),
    status text not null default 'planning'
        check (status in ('planning', 'active', 'completed'))
);

create index tours_owner_user_id_idx on public.tours(owner_user_id);

-- ---------------------------------------------------------------------------
-- tour_participants  (many-to-many; controls visibility/edit access via RLS)
-- ---------------------------------------------------------------------------
create table public.tour_participants (
    tour_id uuid not null references public.tours(id) on delete cascade,
    user_id uuid not null references public.users(id) on delete cascade,
    role text check (role in ('buyer', 'partner', 'agent')),
    invited_at timestamptz not null default now(),
    joined_at timestamptz,
    primary key (tour_id, user_id)
);

create index tour_participants_user_id_idx on public.tour_participants(user_id);

-- ---------------------------------------------------------------------------
-- tour_invites  (magic-link invite flow target)
-- ---------------------------------------------------------------------------
create table public.tour_invites (
    id uuid primary key default gen_random_uuid(),
    tour_id uuid not null references public.tours(id) on delete cascade,
    email text not null,
    role text check (role in ('buyer', 'partner', 'agent')),
    token text not null unique,
    expires_at timestamptz not null,
    accepted_at timestamptz
);

create index tour_invites_tour_id_idx on public.tour_invites(tour_id);
create index tour_invites_email_idx on public.tour_invites(email);

-- ---------------------------------------------------------------------------
-- houses
-- ---------------------------------------------------------------------------
create table public.houses (
    id uuid primary key default gen_random_uuid(),
    tour_id uuid not null references public.tours(id) on delete cascade,
    address text not null,
    list_price numeric,
    sqft integer,
    beds numeric,
    baths numeric,
    listing_url text,
    scheduled_at timestamptz,
    status text not null default 'upcoming'
        check (status in ('upcoming', 'touring', 'completed')),
    overall_score numeric,
    overall_notes text,
    bot_id text,
    audio_url text,
    video_url text,
    synthesis_md text
);

create index houses_tour_id_idx on public.houses(tour_id);
create index houses_bot_id_idx on public.houses(bot_id);

-- ---------------------------------------------------------------------------
-- observations  (the unified core; every UI view derives from it)
-- ---------------------------------------------------------------------------
create table public.observations (
    id uuid primary key default gen_random_uuid(),
    house_id uuid not null references public.houses(id) on delete cascade,
    user_id uuid references public.users(id) on delete set null,
    room text,
    category text not null check (category in (
        'layout', 'condition', 'hazard', 'positive',
        'concern', 'agent_said', 'partner_said'
    )),
    content text not null,
    severity text check (severity in ('info', 'warn', 'critical')),
    source text not null check (source in ('manual', 'transcript', 'photo_analysis')),
    created_at timestamptz not null default now(),
    recall_timestamp numeric  -- seconds into the meeting; column name kept generic for v2 swap
);

create index observations_house_id_idx on public.observations(house_id);
create index observations_house_created_idx on public.observations(house_id, created_at desc);

-- ---------------------------------------------------------------------------
-- transcripts  (raw chunks from Meeting BaaS)
-- ---------------------------------------------------------------------------
create table public.transcripts (
    id uuid primary key default gen_random_uuid(),
    house_id uuid not null references public.houses(id) on delete cascade,
    bot_id text not null,
    speaker text,
    text text not null,
    start_seconds numeric not null,
    end_seconds numeric,
    processed boolean not null default false
);

-- Idempotency key for Meeting BaaS webhook dedupe.
create unique index transcripts_bot_start_uniq
    on public.transcripts(bot_id, start_seconds);

create index transcripts_house_id_idx on public.transcripts(house_id);
create index transcripts_unprocessed_idx
    on public.transcripts(house_id, start_seconds)
    where processed = false;

-- ---------------------------------------------------------------------------
-- Realtime — broadcast observations inserts so the partner's UI updates live.
-- ---------------------------------------------------------------------------
alter publication supabase_realtime add table public.observations;

-- ---------------------------------------------------------------------------
-- Row-level security — enable on every table.
-- Policies deferred to Hours 18–20 polish phase; until then the backend uses
-- the service-role key (which bypasses RLS) and the frontend reads through
-- backend endpoints, not directly from PostgREST.
-- ---------------------------------------------------------------------------
alter table public.users              enable row level security;
alter table public.tours              enable row level security;
alter table public.tour_participants  enable row level security;
alter table public.tour_invites       enable row level security;
alter table public.houses             enable row level security;
alter table public.observations       enable row level security;
alter table public.transcripts        enable row level security;
