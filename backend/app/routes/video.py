"""Upload a tour video recorded outside the app (e.g. iPhone camera roll
when the live multi-party path didn't work). Mirrors the post-meeting
webhook pipeline: extract audio, run vision over frames, run the
existing audio pipeline (Whisper -> extract -> synthesize -> schematic),
and (gated) spawn the measured-floorplan Modal job.

Two-step flow because tour videos are typically 100MB-1GB and Railway's
edge proxy rejects request bodies past ~100MB:

  1. POST /houses/{id}/video/upload-url -> returns a Supabase signed
     upload URL the client uses to PUT the video directly to Storage.
     No Railway in the upload path.
  2. POST /houses/{id}/video/process    -> client tells us the upload is
     done with the storage_path; backend stream-downloads from Storage
     to a temp file (never holds the whole video in memory) and fires
     the analysis pipeline as a BackgroundTask.

The disk-streaming approach keeps Railway memory low: a 368 MB video
spends a few seconds on disk during analysis instead of sitting in
process memory through the whole vision -> ffmpeg -> Whisper sequence.

Distinct from /houses/{id}/audio: that path is audio-only and never
feeds the vision or measured-floor-plan stages."""
import logging
import os
import subprocess
import tempfile
import time
from uuid import uuid4

import httpx
import sentry_sdk
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
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


class SignedUploadResponse(BaseModel):
    signed_url: str
    token: str
    storage_path: str


class ProcessVideoBody(BaseModel):
    storage_path: str


class ProcessVideoResponse(BaseModel):
    house_id: str
    status: str
    duration_seconds: float | None


def _stream_download_to_tempfile(storage_path: str) -> str:
    """Stream-download from Supabase Storage to a NamedTemporaryFile on
    disk. Returns the local file path. Caller must os.unlink() when done.

    Uses a signed download URL + httpx streaming so we never hold the
    whole video in process memory — important on Railway where a 368 MB
    in-memory blob crashed the worker."""
    sb = supabase()
    # Mint a short-lived signed URL we can stream from.
    res = sb.storage.from_("tour-audio").create_signed_url(
        storage_path, expires_in=600
    )
    signed_url = res.get("signed_url") or res.get("signedURL")
    if not signed_url:
        raise RuntimeError(f"create_signed_url returned no URL: {list(res.keys())}")

    fd, path = tempfile.mkstemp(suffix=os.path.splitext(storage_path)[1] or ".mp4")
    os.close(fd)
    bytes_written = 0
    with httpx.stream("GET", signed_url, timeout=600.0, follow_redirects=True) as r:
        r.raise_for_status()
        with open(path, "wb") as out:
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                out.write(chunk)
                bytes_written += len(chunk)
    log.info(
        "video upload: streamed %.1f MB from storage to %s",
        bytes_written / (1024 * 1024),
        path,
    )
    return path


def _extract_audio_wav_to_path(in_path: str, out_path: str) -> bool:
    """ffmpeg-extract a 16 kHz mono WAV from the video at in_path, write
    to out_path. Returns True on success. Path-based to keep memory low."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                in_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                "-y",
                out_path,
            ],
            capture_output=True,
            check=True,
            timeout=900,
        )
        del result
        return True
    except subprocess.CalledProcessError as e:
        log.error(
            "ffmpeg audio-extract failed (rc=%d): %s",
            e.returncode,
            (e.stderr or b"")[:1000].decode("utf-8", "ignore"),
        )
        return False
    except subprocess.TimeoutExpired:
        log.error("ffmpeg audio-extract timed out")
        return False


def _process_video_upload_from_path(
    house_id: str, video_path: str, video_storage_path: str
) -> None:
    """Mirror of webhooks.run_post_meeting_pipeline for an uploaded video,
    operating on a temp-file path so we never hold the whole video in
    memory. Runs vision -> audio pipeline -> (gated) measured floor plan.
    Cleans up the temp file at the end."""
    sb = supabase()

    try:
        # Import here so test/debug imports of this module don't pull in
        # the heavy vision deps.
        from app.llm.vision import (
            analyze_video_at_path,
            probe_video_duration_at_path,
        )

        duration: float | None = None
        try:
            duration = probe_video_duration_at_path(video_path)
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
                log.info(
                    "video upload running vision house=%s path=%s",
                    house_id,
                    video_path,
                )
                visual_obs = analyze_video_at_path(video_path)
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

        # Extract audio to a sibling temp WAV, then read into memory for
        # Whisper. WAV at 16 kHz mono is ~32 KB/s -> ~60 MB for a 30-min
        # tour, comfortable to keep in memory for the existing chunker.
        wav_path = video_path + ".wav"
        ok = _extract_audio_wav_to_path(video_path, wav_path)
        if not ok:
            log.warning(
                "video upload: audio extract failed, marking completed without "
                "transcript-derived obs or synthesis house=%s",
                house_id,
            )
            sb.table("houses").update({"status": "completed"}).eq(
                "id", house_id
            ).execute()
        else:
            try:
                with open(wav_path, "rb") as f:
                    wav_bytes = f.read()
                log.info(
                    "video upload running whisper pipeline house=%s wav_bytes=%d",
                    house_id,
                    len(wav_bytes),
                )
                _process_audio_upload(house_id, wav_bytes, "audio/wav", "wav")
            finally:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

        # Measured floor plan removed in v2.7 — see CHANGELOG. The
        # video bytes still feed the vision pipeline above, but we no
        # longer spawn the Modal floor-plan job.
        log.info(
            "video upload pipeline complete house=%s video_storage_path=%s",
            house_id,
            video_storage_path,
        )
    finally:
        try:
            os.unlink(video_path)
        except Exception:
            pass


@router.post(
    "/houses/{house_id}/video/upload-url",
    response_model=SignedUploadResponse,
)
async def get_video_upload_url(
    house_id: str,
    user: AuthUser = Depends(current_user),
    ext: str = "mp4",
) -> SignedUploadResponse:
    """Mint a Supabase signed upload URL the client can PUT directly to.
    Sidesteps Railway's request-body cap for large videos."""
    get_house_for_user(house_id, user.id)

    safe_ext = ext.lower().lstrip(".")
    if safe_ext not in ("mp4", "mov", "m4v", "webm", "mkv"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported video extension: .{safe_ext}",
        )
    storage_path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.{safe_ext}"

    sb = supabase()
    try:
        res = sb.storage.from_("tour-audio").create_signed_upload_url(storage_path)
    except Exception as e:
        log.exception("create_signed_upload_url failed house=%s", house_id)
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not create upload URL: {e}",
        ) from e

    return SignedUploadResponse(
        signed_url=res["signed_url"],
        token=res["token"],
        storage_path=storage_path,
    )


@router.post(
    "/houses/{house_id}/video/process",
    response_model=ProcessVideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_uploaded_video(
    house_id: str,
    body: ProcessVideoBody,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(current_user),
) -> ProcessVideoResponse:
    """Client has uploaded video to Storage at body.storage_path; download
    (streaming, to a temp file on disk) and run the full analysis pipeline.

    The temp file is the source for vision frame extraction, audio extract,
    and measured floor plan. We never hold the whole video in memory."""
    get_house_for_user(house_id, user.id)

    try:
        video_path = _stream_download_to_tempfile(body.storage_path)
    except Exception as e:
        log.exception(
            "storage stream-download failed house=%s path=%s",
            house_id,
            body.storage_path,
        )
        sentry_sdk.capture_exception(e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not fetch uploaded video from storage: {e}",
        ) from e

    # Probe duration synchronously so the response includes it.
    from app.llm.vision import probe_video_duration_at_path

    duration = probe_video_duration_at_path(video_path)

    sb = supabase()
    sb.table("houses").update(
        {
            "video_url": body.storage_path,
            "status": "synthesizing",
            "tour_started_at": "now()",
            "video_duration_seconds": duration,
        }
    ).eq("id", house_id).execute()

    background_tasks.add_task(
        _process_video_upload_from_path,
        house_id,
        video_path,
        body.storage_path,
    )

    return ProcessVideoResponse(
        house_id=house_id,
        status="synthesizing",
        duration_seconds=duration,
    )
