"""Meeting BaaS webhook receiver: status_change + bot.completed.

Status events flip the house row's status. Completion downloads the bot's
recording + transcript artifacts (presigned S3, 4h TTL) into our Supabase
Storage bucket and triggers the Sonnet synthesis pass — same downstream as
Hours 3-8.
"""

import json
import logging
import time
from uuid import uuid4

import httpx
import sentry_sdk
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.config import settings
from app.db.supabase import supabase
from app.llm.synthesize import synthesize_house
from app.providers.meetingbaas import get_meeting_provider
from app.realtime import state

log = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


def _house_for_bot(bot_id: str) -> dict | None:
    sb = supabase()
    res = sb.table("houses").select("*").eq("bot_id", bot_id).limit(1).execute()
    return res.data[0] if res.data else None


def _download_to_storage(url: str, house_id: str, suffix: str) -> str | None:
    """Stream a presigned URL into our private Supabase bucket. Returns the path."""
    try:
        with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as r:
            r.raise_for_status()
            content = b"".join(r.iter_bytes())
    except Exception as e:
        log.exception("download from %s failed", url[:80])
        sentry_sdk.capture_exception(e)
        return None

    path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.{suffix}"
    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=path,
        file=content,
        file_options={"content-type": "application/octet-stream", "upsert": "true"},
    )
    return path


def _download_audio(url: str, house_id: str) -> tuple[str | None, bytes | None]:
    """Download audio + upload to storage. Returns (path, bytes) so the
    caller can both archive and re-process without a second download."""
    try:
        with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as r:
            r.raise_for_status()
            content = b"".join(r.iter_bytes())
    except Exception as e:
        log.exception("audio download from %s failed", url[:80])
        sentry_sdk.capture_exception(e)
        return None, None

    path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.wav"
    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=path,
        file=content,
        file_options={"content-type": "audio/wav", "upsert": "true"},
    )
    return path, content


def _backfill_transcripts_from_url(
    transcript_url: str, house_id: str, bot_id: str
) -> int:
    """If the live stream missed everything, parse the post-meeting transcript file
    and insert into transcripts. Skipped if we already have live rows for this bot.
    """
    sb = supabase()
    existing = (
        sb.table("transcripts")
        .select("id", count="exact")
        .eq("bot_id", bot_id)
        .execute()
    )
    if existing.count and existing.count > 0:
        return 0

    try:
        r = httpx.get(transcript_url, timeout=60.0, follow_redirects=True)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.exception("transcript backfill download failed")
        sentry_sdk.capture_exception(e)
        return 0

    rows = []
    for seg in data if isinstance(data, list) else data.get("segments", []):
        words = seg.get("words") or []
        if not words:
            continue
        text = (seg.get("text") or " ".join(w.get("word", "") for w in words)).strip()
        if not text:
            continue
        rows.append(
            {
                "house_id": house_id,
                "bot_id": bot_id,
                "speaker": seg.get("speaker"),
                "text": text,
                "start_seconds": float(words[0].get("start", 0.0)),
                "end_seconds": float(words[-1].get("end", 0.0)),
                "processed": False,
            }
        )

    if rows:
        try:
            sb.table("transcripts").insert(rows).execute()
        except Exception as e:
            log.exception("transcript backfill insert failed")
            sentry_sdk.capture_exception(e)
    return len(rows)


def _finalize(bot_id: str, payload: dict) -> None:
    """BG task triggered by bot.completed."""
    log.info("_finalize start bot=%s payload_keys=%s", bot_id, list(payload.keys()))
    try:
        _finalize_inner(bot_id, payload)
        log.info("_finalize ok bot=%s", bot_id)
    except Exception as e:
        log.exception("_finalize crashed bot=%s", bot_id)
        sentry_sdk.capture_exception(e)


def _finalize_inner(bot_id: str, payload: dict) -> None:
    house = _house_for_bot(bot_id)
    if not house:
        log.warning("bot.completed for unknown bot %s", bot_id)
        return
    house_id = house["id"]
    sb = supabase()

    completion = get_meeting_provider().parse_completion_webhook(payload)
    if not completion:
        log.warning(
            "could not parse completion payload for bot %s, payload data keys=%s",
            bot_id,
            list((payload.get("data") or {}).keys()),
        )
        return
    log.info(
        "_finalize parsed bot=%s audio=%s video=%s transcript=%s",
        bot_id,
        bool(completion.get("audio_url")),
        bool(completion.get("video_url")),
        bool(completion.get("transcript_url")),
    )

    audio_path = video_path = None
    audio_bytes: bytes | None = None
    if completion.get("audio_url"):
        audio_path, audio_bytes = _download_audio(
            completion["audio_url"], house_id
        )
    if completion.get("video_url"):
        video_path = _download_to_storage(completion["video_url"], house_id, "mp4")

    update: dict = {"status": "synthesizing"}
    if audio_path:
        update["audio_url"] = audio_path
    if video_path:
        update["video_url"] = video_path
    sb.table("houses").update(update).eq("id", house_id).execute()

    if not audio_bytes:
        log.warning("no audio bytes for bot %s, marking completed", bot_id)
        sb.table("houses").update({"status": "completed"}).eq(
            "id", house_id
        ).execute()
        state.drop(bot_id)
        return

    # Reuse the Hours 3-8 pipeline: Whisper -> chunks -> extract -> synthesize.
    # MB's bundled diarization-only transcript doesn't include text in many v1
    # payloads, so we always run our own Whisper pass on the recording.
    from app.routes.audio import _process_audio_upload

    log.info("_finalize running whisper pipeline bot=%s", bot_id)
    _process_audio_upload(house_id, audio_bytes, "audio/wav", "wav")
    state.drop(bot_id)


@router.post("/webhooks/meetingbaas", status_code=status.HTTP_200_OK)
async def meetingbaas_webhook(
    request: Request, background: BackgroundTasks
) -> dict:
    body = await request.body()
    headers = dict(request.headers)

    log.info(
        "mb webhook headers: %s",
        {k: v for k, v in headers.items() if not k.lower().startswith("x-railway-")},
    )

    provider = get_meeting_provider()
    if settings.meetingbaas_verify_webhook:
        if not provider.verify_webhook_signature(headers, body):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    else:
        log.warning("mb webhook signature verification BYPASSED (dev/MVP mode)")

    payload = json.loads(body)
    event = payload.get("event")
    data_keys = list((payload.get("data") or {}).keys())
    log.info("mb webhook event=%s data_keys=%s", event, data_keys)

    if event == "bot.completed" or event == "complete":
        bot_id = (payload.get("data") or {}).get("bot_id")
        if bot_id:
            background.add_task(_finalize, bot_id, payload)
        return {"ok": True}

    parsed = provider.parse_status_webhook(payload)
    if parsed:
        sb = supabase()
        if parsed["code"] in ("call_ended", "in_call_not_recording"):
            sb.table("houses").update({"status": "synthesizing"}).eq(
                "bot_id", parsed["bot_id"]
            ).execute()

    return {"ok": True}
