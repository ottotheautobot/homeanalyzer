-- Add transcripts to the supabase_realtime publication so the house page
-- can show live captions as MB+Deepgram produce them. Observations still
-- arrive every ~20s on extraction; transcripts give an immediate "the bot
-- is hearing you" signal in between.

do $$ begin
  alter publication supabase_realtime add table public.transcripts;
exception when duplicate_object then null;
end $$;
