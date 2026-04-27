import logging
import time
from uuid import uuid4

import sentry_sdk
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user
from app.llm.extract import extract_observations
from app.llm.synthesize import synthesize_house
from app.llm.whisper import transcribe
from app.routes.houses import get_house_for_user

router = APIRouter(tags=["audio"])
log = logging.getLogger(__name__)

EXTRACTION_WINDOW_SECONDS = 60.0


class UploadResponse(BaseModel):
    house_id: str
    status: str
    storage_path: str


def _process_audio_upload(
    house_id: str, audio_bytes: bytes, mime: str, ext: str
) -> None:
    """Pipeline: Whisper -> transcripts -> 60s windows -> extract -> observations -> synthesize."""
    sb = supabase()
    bot_id = f"upload:{uuid4().hex}"

    try:
        chunks = transcribe(audio_bytes, filename=f"{house_id}.{ext}", mime=mime)
    except Exception as e:
        log.exception("transcription failed for house %s", house_id)
        sentry_sdk.capture_exception(e)
        return

    if not chunks:
        sb.table("houses").update({"status": "completed"}).eq("id", house_id).execute()
        return

    sb.table("transcripts").insert(
        [
            {
                "house_id": house_id,
                "bot_id": bot_id,
                "speaker": c["speaker"],
                "text": c["text"],
                "start_seconds": c["start_seconds"],
                "end_seconds": c["end_seconds"],
                "processed": False,
            }
            for c in chunks
        ]
    ).execute()

    end_time = max(c["end_seconds"] for c in chunks)
    recent_obs: list[dict] = []
    t = 0.0
    while t < end_time:
        window = [
            c for c in chunks if t <= c["start_seconds"] < t + EXTRACTION_WINDOW_SECONDS
        ]
        if window:
            try:
                new_obs = extract_observations(window, recent_obs, room_hint=None)
            except Exception as e:
                log.exception("extraction failed at t=%s for house %s", t, house_id)
                sentry_sdk.capture_exception(e)
                new_obs = []
            if new_obs:
                rows = [
                    {
                        "house_id": house_id,
                        "user_id": None,
                        "room": o.get("room"),
                        "category": o["category"],
                        "content": o["content"],
                        "severity": o.get("severity"),
                        "source": "transcript",
                        "recall_timestamp": (
                            o.get("recall_timestamp")
                            if o.get("recall_timestamp") is not None
                            else window[0]["start_seconds"]
                        ),
                    }
                    for o in new_obs
                ]
                sb.table("observations").insert(rows).execute()
                recent_obs.extend(new_obs)
        t += EXTRACTION_WINDOW_SECONDS

    sb.table("transcripts").update({"processed": True}).eq("house_id", house_id).eq(
        "bot_id", bot_id
    ).execute()

    house_res = sb.table("houses").select("*").eq("id", house_id).limit(1).execute()
    if not house_res.data:
        return
    obs_res = (
        sb.table("observations")
        .select("*")
        .eq("house_id", house_id)
        .order("created_at", desc=False)
        .execute()
    )

    try:
        synthesis = synthesize_house(house_res.data[0], chunks, obs_res.data)
    except Exception as e:
        log.exception("synthesis failed for house %s", house_id)
        sentry_sdk.capture_exception(e)
        sb.table("houses").update({"status": "completed"}).eq("id", house_id).execute()
        return

    sb.table("houses").update(
        {
            "status": "completed",
            "synthesis_md": synthesis["synthesis_md"],
            "overall_score": synthesis["overall_score"],
        }
    ).eq("id", house_id).execute()


@router.post(
    "/houses/{house_id}/audio",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_audio(
    house_id: str,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
) -> UploadResponse:
    get_house_for_user(house_id, user.id)

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty audio file")

    filename = audio.filename or "audio.mp3"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp3"
    storage_path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.{ext}"
    mime = audio.content_type or "audio/mpeg"

    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=storage_path,
        file=audio_bytes,
        file_options={"content-type": mime, "upsert": "true"},
    )

    sb.table("houses").update(
        {
            "audio_url": storage_path,
            "status": "touring",
            "tour_started_at": "now()",
        }
    ).eq("id", house_id).execute()

    background_tasks.add_task(_process_audio_upload, house_id, audio_bytes, mime, ext)

    return UploadResponse(
        house_id=house_id, status="touring", storage_path=storage_path
    )
