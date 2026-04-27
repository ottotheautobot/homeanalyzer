"""Meeting BaaS webhook receiver: status_change + bot.completed.

Status events flip the house row's status. Completion downloads the bot's
recording + transcript artifacts (presigned S3, 4h TTL) into our Supabase
Storage bucket and triggers the Sonnet synthesis pass — same downstream as
Hours 3-8.
"""

import json
import logging
import time
from datetime import datetime, timezone
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


def _compress_wav_to_opus(wav_bytes: bytes) -> bytes | None:
    """Re-encode a WAV to opus-in-ogg via ffmpeg. ~12x smaller for typical
    tour audio (24 kHz mono speech). Returns None on any ffmpeg failure so
    callers can fall back to uploading the raw WAV."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-application",
                "voip",
                "-f",
                "ogg",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            timeout=180,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        log.error(
            "ffmpeg opus encode failed: %s",
            e.stderr.decode("utf-8", "ignore")[:500],
        )
        return None
    except Exception:
        log.exception("audio compression crashed")
        return None


def _download_audio(url: str, house_id: str) -> tuple[str | None, bytes | None]:
    """Download audio + upload to storage. Returns (path, bytes) so the
    caller can both archive and re-process without a second download.

    Storage upload is opus-compressed (saved as .ogg) because the raw WAV
    from Meeting BaaS often exceeds Supabase Storage's per-object limit on
    long tours — opus is ~12x smaller with no transcription quality loss.
    The in-memory bytes returned are still the raw WAV so the existing
    Whisper chunker in app.llm.whisper keeps working unchanged."""
    try:
        with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as r:
            r.raise_for_status()
            content = b"".join(r.iter_bytes())
    except Exception as e:
        log.exception("audio download from %s failed", url[:80])
        sentry_sdk.capture_exception(e)
        return None, None

    opus = _compress_wav_to_opus(content)
    if opus is not None:
        path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.ogg"
        upload_bytes = opus
        upload_mime = "audio/ogg"
        log.info(
            "audio compressed: wav=%d B -> opus=%d B (%.1fx)",
            len(content),
            len(opus),
            len(content) / max(len(opus), 1),
        )
    else:
        # Fall back to raw WAV. May still fail if it's bigger than the
        # bucket limit, but caller will get None and degrade gracefully.
        path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.wav"
        upload_bytes = content
        upload_mime = "audio/wav"

    sb = supabase()
    try:
        sb.storage.from_("tour-audio").upload(
            path=path,
            file=upload_bytes,
            file_options={"content-type": upload_mime, "upsert": "true"},
        )
    except Exception as e:
        log.exception("audio upload to storage failed")
        sentry_sdk.capture_exception(e)
        # Still return the in-memory bytes so synthesis can run from RAM
        # even if archival failed — better partial success than nothing.
        return None, content
    return path, content


def _download_video(url: str, house_id: str) -> tuple[str | None, bytes | None]:
    """Download video + upload to storage. Returns (path, bytes)."""
    try:
        with httpx.stream("GET", url, timeout=600.0, follow_redirects=True) as r:
            r.raise_for_status()
            content = b"".join(r.iter_bytes())
    except Exception as e:
        log.exception("video download from %s failed", url[:80])
        sentry_sdk.capture_exception(e)
        return None, None

    path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.mp4"
    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=path,
        file=content,
        file_options={"content-type": "video/mp4", "upsert": "true"},
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
    completion = get_meeting_provider().parse_completion_webhook(payload)
    if not completion:
        log.warning(
            "could not parse completion payload for bot %s, payload data keys=%s",
            bot_id,
            list((payload.get("data") or {}).keys()),
        )
        return
    run_post_meeting_pipeline(house, completion)


def run_post_meeting_pipeline(house: dict, completion) -> None:
    """Core post-meeting work given a normalized CompletionPayload.

    Used by both the webhook handler (initial dispatch) and the manual
    retry route (when an earlier finalize crashed before persisting,
    e.g. the WAV-too-big incident from earlier today)."""
    bot_id = str(completion.get("bot_id", ""))
    house_id = house["id"]
    sb = supabase()

    log.info(
        "_finalize parsed bot=%s audio=%s video=%s transcript=%s",
        bot_id,
        bool(completion.get("audio_url")),
        bool(completion.get("video_url")),
        bool(completion.get("transcript_url")),
    )

    audio_path = video_path = None
    audio_bytes: bytes | None = None
    video_bytes: bytes | None = None
    if completion.get("audio_url"):
        audio_path, audio_bytes = _download_audio(
            completion["audio_url"], house_id
        )
    if completion.get("video_url"):
        video_path, video_bytes = _download_video(
            completion["video_url"], house_id
        )

    update: dict = {"status": "synthesizing"}
    if audio_path:
        update["audio_url"] = audio_path
    if video_path:
        update["video_url"] = video_path
    if video_bytes:
        try:
            from app.llm.vision import probe_video_duration

            dur = probe_video_duration(video_bytes)
            if dur is not None:
                update["video_duration_seconds"] = dur
                log.info("_finalize video duration bot=%s seconds=%.1f", bot_id, dur)
        except Exception as e:
            log.exception("video duration probe failed bot=%s", bot_id)
            sentry_sdk.capture_exception(e)
    sb.table("houses").update(update).eq("id", house_id).execute()

    if not audio_bytes:
        log.warning("no audio bytes for bot %s, marking completed", bot_id)
        sb.table("houses").update({"status": "completed"}).eq(
            "id", house_id
        ).execute()
        state.drop(bot_id)
        return

    # Vision pass on the video first (if available) so the visual observations
    # land before synthesis runs and Sonnet can fold them into the brief.
    if video_bytes and settings.enable_vision_analysis:
        try:
            from app.llm.vision import analyze_video

            log.info("_finalize running vision bot=%s video_bytes=%d", bot_id, len(video_bytes))
            visual_obs = analyze_video(video_bytes)
            if visual_obs:
                rows = [
                    {
                        "house_id": house_id,
                        "user_id": None,
                        "room": o.get("room"),
                        "category": o["category"],
                        "content": o["content"],
                        "severity": o.get("severity"),
                        "source": "photo_analysis",
                        "recall_timestamp": o.get("recall_timestamp"),
                    }
                    for o in visual_obs
                ]
                sb.table("observations").insert(rows).execute()
                log.info("_finalize wrote %d visual observations bot=%s", len(rows), bot_id)
        except Exception as e:
            log.exception("vision pipeline crashed bot=%s", bot_id)
            sentry_sdk.capture_exception(e)

    # Reuse the Hours 3-8 pipeline: Whisper -> chunks -> extract -> synthesize.
    # MB's bundled diarization-only transcript doesn't include text in many v1
    # payloads, so we always run our own Whisper pass on the recording.
    # Synthesis at the end picks up both audio + photo_analysis observations.
    from app.routes.audio import _process_audio_upload

    log.info("_finalize running whisper pipeline bot=%s", bot_id)
    _process_audio_upload(house_id, audio_bytes, "audio/wav", "wav")

    # Measured floor plan: fire-and-forget on Modal if the feature is on and
    # we have a video to feed it. Blocking would keep the webhook handler
    # busy for ~5 min; instead we schedule the same background task that the
    # manual button triggers via the measured_floorplan route.
    if (
        settings.enable_measured_floorplan
        and update.get("video_url")
        and update.get("video_duration_seconds", 0) >= 30
    ):
        try:
            from app.routes.measured_floorplan import spawn_modal_job

            # Re-read the schematic from DB — synthesis just wrote it.
            fresh = (
                sb.table("houses")
                .select("floor_plan_json,video_url")
                .eq("id", house_id)
                .single()
                .execute()
            )
            schematic = (fresh.data or {}).get("floor_plan_json")

            sb.table("houses").update(
                {
                    "measured_floor_plan_status": "pending",
                    "measured_floor_plan_error": None,
                    "measured_floor_plan_started_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "measured_floor_plan_modal_call_id": None,
                }
            ).eq("id", house_id).execute()

            # Modal.spawn() returns immediately with a FunctionCall id we
            # persist on the row. The frontend polls measure-floorplan-poll
            # to retrieve the result — no daemon thread needed, so a Railway
            # worker restart doesn't lose the job.
            call_id = spawn_modal_job(
                house_id=house_id,
                video_storage_path=update["video_url"],
                schematic=schematic,
            )
            if call_id:
                sb.table("houses").update(
                    {"measured_floor_plan_modal_call_id": call_id}
                ).eq("id", house_id).execute()
                log.info(
                    "_finalize spawned measured floor-plan house=%s call_id=%s "
                    "(schematic_rooms=%d)",
                    house_id,
                    call_id,
                    len((schematic or {}).get("rooms") or []),
                )
        except Exception as e:
            log.exception("failed to spawn measured floor-plan job house=%s", house_id)
            sentry_sdk.capture_exception(e)

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
    data = payload.get("data") or {}
    data_keys = list(data.keys())
    status_code = (data.get("status") or {}).get("code") if isinstance(data.get("status"), dict) else None
    error_message = (data.get("status") or {}).get("error_message") if isinstance(data.get("status"), dict) else None
    log.info(
        "mb webhook event=%s status_code=%s error=%s data_keys=%s",
        event, status_code, error_message, data_keys,
    )

    if event == "bot.completed" or event == "complete":
        bot_id = (payload.get("data") or {}).get("bot_id")
        if bot_id:
            background.add_task(_finalize, bot_id, payload)
        return {"ok": True}

    parsed = provider.parse_status_webhook(payload)
    if parsed:
        sb = supabase()
        # Only call_ended is terminal. in_call_not_recording is transient
        # (e.g. between joining the call and starting the recording, or a
        # brief pause); flipping status on it would make the live UI hide
        # itself mid-tour even though the bot is still in the meeting.
        if parsed["code"] == "call_ended":
            sb.table("houses").update({"status": "synthesizing"}).eq(
                "bot_id", parsed["bot_id"]
            ).execute()

    return {"ok": True}
