"""Upload a tour video recorded outside the app (e.g. Voice Memos / iPhone
camera roll when the live multi-party path didn't work). Mirrors the
post-meeting webhook pipeline: extract audio, run vision over frames,
run the existing audio pipeline (Whisper -> extract -> synthesize ->
schematic), and (gated) spawn the measured-floorplan Modal job.

Distinct from /houses/{id}/audio: that path is audio-only and never feeds
the vision or measured-floor-plan stages."""
import logging
import subprocess
import time
from datetime import datetime, timezone
from uuid import uuid4

import sentry_sdk
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.config import settings
from app.db.supabase import supabase
from app.deps import AuthUser, current_user
from app.routes.audio import _process_audio_upload
from app.routes.houses import get_house_for_user

router = APIRouter(tags=["video"])
log = logging.getLogger(__name__)


class UploadVideoResponse(BaseModel):
    house_id: str
    status: str
    video_storage_path: str
    duration_seconds: float | None


def _extract_audio_wav(video_bytes: bytes) -> bytes | None:
    """ffmpeg-extract a 16 kHz mono WAV from the video. Whisper prefers
    16 kHz mono and the existing _split_wav helper handles WAV chunking
    when audio exceeds Whisper's 25 MB limit."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                "pipe:1",
            ],
            input=video_bytes,
            capture_output=True,
            check=True,
            timeout=600,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        log.error(
            "ffmpeg audio-extract failed (rc=%d): %s",
            e.returncode,
            (e.stderr or b"")[:1000].decode("utf-8", "ignore"),
        )
        return None
    except subprocess.TimeoutExpired:
        log.error("ffmpeg audio-extract timed out")
        return None


def _process_video_upload(
    house_id: str, video_bytes: bytes, video_storage_path: str
) -> None:
    """Mirror of webhooks.run_post_meeting_pipeline for an uploaded video.
    Runs vision -> audio pipeline -> (gated) measured floor plan."""
    sb = supabase()

    # Probe duration for the row + the measured-floorplan gate.
    duration: float | None = None
    try:
        from app.llm.vision import probe_video_duration

        duration = probe_video_duration(video_bytes)
        if duration is not None:
            sb.table("houses").update(
                {"video_duration_seconds": duration}
            ).eq("id", house_id).execute()
    except Exception as e:
        log.exception("video duration probe failed for house %s", house_id)
        sentry_sdk.capture_exception(e)

    # Vision pass on the video frames first so visual observations land
    # before synthesis; matches the webhook flow.
    if settings.enable_vision_analysis:
        try:
            from app.llm.vision import analyze_video

            log.info(
                "video upload running vision house=%s bytes=%d",
                house_id,
                len(video_bytes),
            )
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
                log.info(
                    "video upload wrote %d visual observations house=%s",
                    len(rows),
                    house_id,
                )
        except Exception as e:
            log.exception("vision pipeline crashed house=%s", house_id)
            sentry_sdk.capture_exception(e)

    # Extract audio for the Whisper -> extract -> synthesize -> schematic
    # pipeline. Even if extraction fails we keep the video + vision obs.
    wav_bytes = _extract_audio_wav(video_bytes)
    if not wav_bytes:
        log.warning(
            "video upload: audio extract failed, marking completed without "
            "transcript-derived obs or synthesis house=%s",
            house_id,
        )
        sb.table("houses").update({"status": "completed"}).eq(
            "id", house_id
        ).execute()
    else:
        log.info(
            "video upload running whisper pipeline house=%s wav_bytes=%d",
            house_id,
            len(wav_bytes),
        )
        _process_audio_upload(house_id, wav_bytes, "audio/wav", "wav")

    # Measured floor plan: same gating as the webhook flow.
    skip_reasons = []
    if not settings.enable_measured_floorplan:
        skip_reasons.append("ENABLE_MEASURED_FLOORPLAN=false")
    if (duration or 0) < 30:
        skip_reasons.append(f"duration={duration} < 30s")
    if skip_reasons:
        log.warning(
            "video upload: measured floor plan SKIPPED house=%s: %s",
            house_id,
            "; ".join(skip_reasons),
        )
        return

    try:
        from app.routes.measured_floorplan import spawn_modal_job

        fresh = (
            sb.table("houses")
            .select("floor_plan_json")
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

        call_id = spawn_modal_job(
            house_id=house_id,
            video_storage_path=video_storage_path,
            schematic=schematic,
        )
        if call_id:
            sb.table("houses").update(
                {"measured_floor_plan_modal_call_id": call_id}
            ).eq("id", house_id).execute()
            log.info(
                "video upload spawned measured floor plan house=%s call=%s",
                house_id,
                call_id,
            )
    except Exception as e:
        log.exception("video upload: measured floor plan spawn crashed house=%s", house_id)
        sentry_sdk.capture_exception(e)


@router.post(
    "/houses/{house_id}/video",
    response_model=UploadVideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_video(
    house_id: str,
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
) -> UploadVideoResponse:
    """Upload a recorded tour video and run it through the full analysis
    pipeline (vision + transcript-derived observations + synthesis +
    schematic + measured floor plan when the gate is on).

    Use case: tour where the live Meeting BaaS path wasn't usable (no
    signal, app failure, etc.) and you have the camera-roll video.
    """
    get_house_for_user(house_id, user.id)

    video_bytes = await video.read()
    if not video_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty video file")

    filename = video.filename or "tour.mp4"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp4"
    if ext not in ("mp4", "mov", "m4v", "webm", "mkv"):
        # Whisper + ffmpeg are tolerant, but flag obviously-wrong inputs
        # rather than burn a Modal call on something that won't decode.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported video extension: .{ext}",
        )
    storage_path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.{ext}"
    mime = video.content_type or "video/mp4"

    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=storage_path,
        file=video_bytes,
        file_options={"content-type": mime, "upsert": "true"},
    )

    # Mark as synthesizing immediately — the pipeline below will flip to
    # completed (or stay synthesizing on partial-failure paths).
    sb.table("houses").update(
        {
            "video_url": storage_path,
            "status": "synthesizing",
            "tour_started_at": "now()",
        }
    ).eq("id", house_id).execute()

    background_tasks.add_task(
        _process_video_upload, house_id, video_bytes, storage_path
    )

    # Probe duration synchronously so the response includes it — small
    # cost (a few hundred ms) for a much better client UX.
    duration: float | None = None
    try:
        from app.llm.vision import probe_video_duration

        duration = probe_video_duration(video_bytes)
    except Exception:
        pass

    return UploadVideoResponse(
        house_id=house_id,
        status="synthesizing",
        video_storage_path=storage_path,
        duration_seconds=duration,
    )
