-- Hours 8–14: Real-time multi-party tour columns + status.
-- Paste into Supabase SQL editor and run.

-- houses.status gets a transitional 'synthesizing' state for the window
-- between bot leaving the meeting and Sonnet finishing the synthesis pass.
alter table public.houses
    drop constraint if exists houses_status_check;
alter table public.houses
    add constraint houses_status_check
    check (status in ('upcoming', 'touring', 'synthesizing', 'completed'));

-- Sticky room hint set by the "Next Room" button during a live tour.
-- Read by the realtime extractor as a strong prior for room classification.
alter table public.houses
    add column if not exists current_room text;

-- Convenience: track when bot streaming began so Deepgram-emitted timestamps
-- can be mapped to seconds-into-tour even if the bot reconnects mid-tour.
alter table public.houses
    add column if not exists tour_started_at timestamptz;
