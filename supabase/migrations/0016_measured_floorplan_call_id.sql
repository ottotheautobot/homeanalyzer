-- Persist the Modal FunctionCall id so we can poll for the result from any
-- worker instead of holding a blocking call open in a daemon thread that
-- dies when Railway restarts mid-job.

alter table public.houses
    add column if not exists measured_floor_plan_modal_call_id text;
