"""60s rolling extraction trigger for live tours.

Called on each Deepgram final and on every "Next Room" event. Looks at the
unprocessed transcripts for this bot, runs Haiku extraction, writes
observations, marks the chunks processed. The lock on BotState prevents
overlapping runs from the same trigger source.
"""

import logging
import time

import sentry_sdk

from app.db.supabase import supabase
from app.llm.extract import extract_observations
from app.realtime import state

log = logging.getLogger(__name__)

# Trigger extraction every 20s OR when 5+ unprocessed transcripts have piled
# up — whichever comes first. Brief locked 60s; reduced for live UX so the
# observation feed feels responsive rather than batched.
EXTRACTION_WINDOW_SECONDS = 20.0
EXTRACTION_TRANSCRIPT_THRESHOLD = 5


async def maybe_extract(bot_id: str, force: bool = False) -> int:
    """Run extraction if window elapsed, threshold reached, or forced.

    Returns the number of new observations written.
    """
    s = state.get(bot_id)
    if s is None:
        return 0
    now = time.monotonic()
    elapsed = now - s.last_extraction_at
    if not force and elapsed < EXTRACTION_WINDOW_SECONDS:
        # Allow earlier trigger if enough transcripts have piled up.
        from app.db.supabase import supabase as _sb

        count = (
            _sb()
            .table("transcripts")
            .select("id", count="exact")
            .eq("bot_id", bot_id)
            .eq("processed", False)
            .execute()
            .count
            or 0
        )
        if count < EXTRACTION_TRANSCRIPT_THRESHOLD:
            return 0

    if s.extraction_lock.locked():
        return 0
    async with s.extraction_lock:
        s.last_extraction_at = time.monotonic()
        return _extract_for(s.bot_id, s.house_id, s.current_room)


def _extract_for(bot_id: str, house_id: str, room_hint: str | None) -> int:
    sb = supabase()
    rows = (
        sb.table("transcripts")
        .select("id, speaker, text, start_seconds, end_seconds")
        .eq("bot_id", bot_id)
        .eq("processed", False)
        .order("start_seconds")
        .execute()
    )
    if not rows.data:
        return 0

    chunks = [
        {
            "speaker": r.get("speaker"),
            "text": r["text"],
            "start_seconds": float(r["start_seconds"]),
            "end_seconds": float(r["end_seconds"] or r["start_seconds"]),
        }
        for r in rows.data
    ]

    recent = (
        sb.table("observations")
        .select("room, category, content")
        .eq("house_id", house_id)
        .order("created_at", desc=True)
        .limit(30)
        .execute()
    )
    recent_obs = list(reversed(recent.data or []))

    try:
        new_obs = extract_observations(chunks, recent_obs, room_hint=room_hint)
    except Exception as e:
        log.exception("realtime extraction failed for bot %s", bot_id)
        sentry_sdk.capture_exception(e)
        return 0

    if new_obs:
        sb.table("observations").insert(
            [
                {
                    "house_id": house_id,
                    "user_id": None,
                    "room": o.get("room") or room_hint,
                    "category": o["category"],
                    "content": o["content"],
                    "severity": o.get("severity"),
                    "source": "transcript",
                    "recall_timestamp": (
                        o.get("recall_timestamp")
                        if o.get("recall_timestamp") is not None
                        else chunks[0]["start_seconds"]
                    ),
                }
                for o in new_obs
            ]
        ).execute()

    sb.table("transcripts").update({"processed": True}).in_(
        "id", [r["id"] for r in rows.data]
    ).execute()

    return len(new_obs)
