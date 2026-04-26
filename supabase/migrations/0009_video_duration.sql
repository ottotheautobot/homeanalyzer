-- Track the actual video duration (in seconds) on the house row so the UI
-- can hide the recording player when the bot recorded with camera off
-- (1-2 frame mp4 = nothing useful to replay or analyze).

alter table public.houses
    add column if not exists video_duration_seconds numeric;
