"""Vision-augmented observations from the post-meeting recording.

Pipeline:
1. Extract scene-change frames from the mp4 with ffmpeg (5s base interval,
   scene-detect filter dedupes near-identical static stretches).
2. Resize to 768px wide so the per-image token cost stays manageable.
3. Batch ~30 frames per Haiku 4.5 call with a record_observations tool that
   matches the existing observations schema.
4. Return rows ready to insert into the observations table with
   source='photo_analysis' and recall_timestamp = frame's seconds-into-tour.
"""

import base64
import io
import json
import logging
import os
import subprocess
import tempfile
from functools import lru_cache
from typing import TypedDict

import anthropic
import sentry_sdk

from app.config import settings

log = logging.getLogger(__name__)

VISION_MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 4096

FRAME_INTERVAL_SECONDS = 5.0
SCENE_THRESHOLD = 0.05  # ffmpeg `select=gt(scene,X)` — keeps frames with >5% change
FRAME_WIDTH = 768
FRAMES_PER_BATCH = 30


class VisualObservation(TypedDict, total=False):
    room: str | None
    category: str
    content: str
    severity: str | None
    recall_timestamp: float


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def probe_video_duration(mp4_bytes: bytes) -> float | None:
    """Return the duration (seconds) of the video stream in an mp4. None on
    failure. Used to gate UI playback — bots recording with camera off in
    Zoom produce ~1s of video alongside long audio."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(mp4_bytes)
        path = f.name
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if r.returncode != 0:
            return None
        out = r.stdout.decode("utf-8", "ignore").strip()
        return float(out) if out else None
    except Exception:
        return None
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _ffmpeg_extract_frames(
    mp4_bytes: bytes,
) -> list[tuple[float, bytes]]:
    """Run ffmpeg to extract scene-change frames. Returns (seconds, jpeg_bytes)."""
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.mp4")
        out_pattern = os.path.join(td, "f-%05d.jpg")
        with open(in_path, "wb") as f:
            f.write(mp4_bytes)

        # Filter chain:
        #   1. select frames at FRAME_INTERVAL_SECONDS rate
        #   2. dedupe via scene threshold so a static 30s stretch doesn't
        #      contribute 6 near-identical frames
        #   3. scale to FRAME_WIDTH preserving aspect
        # We also write a concurrent "showinfo" log via -metadata to recover
        # source pts; simpler approach: use vsync vfr + select with rate, then
        # parse filenames against original FPS. For robustness here we ask
        # ffmpeg to print the pts via -vf showinfo and parse.
        vf = (
            f"fps=1/{FRAME_INTERVAL_SECONDS},"
            f"select='gt(scene,{SCENE_THRESHOLD})',"
            f"scale={FRAME_WIDTH}:-2,"
            "showinfo"
        )
        cmd = [
            "ffmpeg",
            "-loglevel",
            "info",
            "-i",
            in_path,
            "-vf",
            vf,
            "-vsync",
            "vfr",
            "-q:v",
            "5",
            out_pattern,
        ]

        try:
            r = subprocess.run(
                cmd, capture_output=True, timeout=600, check=False
            )
        except subprocess.TimeoutExpired:
            log.error("ffmpeg timed out extracting frames")
            return []

        if r.returncode != 0:
            log.error("ffmpeg failed: %s", r.stderr.decode("utf-8", "ignore")[:1000])
            return []

        # Parse showinfo output for pts_time per frame.
        timestamps: list[float] = []
        for line in r.stderr.decode("utf-8", "ignore").splitlines():
            if "pts_time:" in line and "[Parsed_showinfo" in line:
                try:
                    after = line.split("pts_time:", 1)[1].strip()
                    secs = float(after.split()[0])
                    timestamps.append(secs)
                except Exception:
                    pass

        # Pair files with timestamps in extraction order.
        files = sorted(
            f for f in os.listdir(td) if f.startswith("f-") and f.endswith(".jpg")
        )
        out: list[tuple[float, bytes]] = []
        for i, name in enumerate(files):
            ts = timestamps[i] if i < len(timestamps) else float(i) * FRAME_INTERVAL_SECONDS
            with open(os.path.join(td, name), "rb") as f:
                out.append((ts, f.read()))
        log.info(
            "ffmpeg extracted %d frames (timestamps parsed=%d)",
            len(out),
            len(timestamps),
        )
        return out


SYSTEM_PROMPT = """You analyze frames from a video recording of a home tour.

You'll receive a batch of frames in chronological order, each tagged with
its seconds-into-tour timestamp. For each frame, identify visual details a
buyer would care about that the audio transcript would NOT capture:

- Visible condition issues (paint chips, water stains, cracks, wear)
- Hazards (exposed wiring, missing rails, mold, pest signs)
- Layout details (room size impressions, ceiling height, window count/quality)
- Quality cues (cabinet/fixture build quality, flooring type, appliances)

Skip:
- Things the audio would obviously cover (the agent talking, the buyer narrating)
- Generic comments not tied to a visible feature ("nice room")
- Duplicates from earlier frames in the batch

Use the record_observations tool. Set:
- category: 'condition' | 'hazard' | 'positive' | 'concern' | 'layout'
- severity (only if hazard or concern): 'info' | 'warn' | 'critical'
- room: brief room/location label if obvious, else null
- content: one short sentence describing the observation
- recall_timestamp: the seconds-into-tour of the frame the observation came from

Empty observations array is fine if a batch shows nothing notable."""

OBSERVATIONS_TOOL = {
    "name": "record_observations",
    "description": "Record visual observations from the analyzed frames.",
    "input_schema": {
        "type": "object",
        "properties": {
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "room": {"type": ["string", "null"]},
                        "category": {
                            "type": "string",
                            "enum": [
                                "layout",
                                "condition",
                                "hazard",
                                "positive",
                                "concern",
                            ],
                        },
                        "content": {"type": "string"},
                        "severity": {
                            "type": ["string", "null"],
                            "enum": ["info", "warn", "critical", None],
                        },
                        "recall_timestamp": {"type": "number"},
                    },
                    "required": ["category", "content", "recall_timestamp"],
                },
            }
        },
        "required": ["observations"],
    },
}


def _vision_call(
    frames: list[tuple[float, bytes]],
) -> list[VisualObservation]:
    """One Haiku call over up to FRAMES_PER_BATCH frames."""
    if not frames:
        return []
    content: list[dict] = []
    for ts, jpeg in frames:
        content.append(
            {
                "type": "text",
                "text": f"Frame at {ts:.1f}s into the tour:",
            }
        )
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(jpeg).decode("ascii"),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                "Call record_observations with all noteworthy visual "
                "observations across these frames."
            ),
        }
    )

    try:
        resp = _client().messages.create(
            model=VISION_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[
                {
                    **OBSERVATIONS_TOOL,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tool_choice={"type": "tool", "name": "record_observations"},
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        log.exception("vision batch failed (%d frames)", len(frames))
        sentry_sdk.capture_exception(e)
        return []

    out: list[VisualObservation] = []
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_observations":
            for o in (block.input or {}).get("observations") or []:
                out.append(o)
    return out


def analyze_video(mp4_bytes: bytes) -> list[VisualObservation]:
    """Top-level entry: extract frames + run vision over batches.

    Returns observations ready to insert; caller fills in house_id/source.
    """
    frames = _ffmpeg_extract_frames(mp4_bytes)
    if not frames:
        return []

    all_obs: list[VisualObservation] = []
    for i in range(0, len(frames), FRAMES_PER_BATCH):
        batch = frames[i : i + FRAMES_PER_BATCH]
        log.info(
            "vision batch %d/%d (%d frames, t=%.1f-%.1fs)",
            i // FRAMES_PER_BATCH + 1,
            (len(frames) + FRAMES_PER_BATCH - 1) // FRAMES_PER_BATCH,
            len(batch),
            batch[0][0],
            batch[-1][0],
        )
        all_obs.extend(_vision_call(batch))
    log.info("vision total observations: %d", len(all_obs))
    return all_obs
