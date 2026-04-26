import io
import logging
import wave
from functools import lru_cache
from typing import TypedDict

from openai import OpenAI

from app.config import settings

log = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-1"
# OpenAI's hard limit is 25 MB. Stay well under to allow for HTTP overhead.
WHISPER_MAX_BYTES = 24 * 1024 * 1024
# When chunking, ~10-min slices keep us well under the limit and produce
# clean segment boundaries (Whisper is fine with mid-sentence cuts; it just
# returns whatever it heard).
CHUNK_SECONDS = 600


class TranscriptChunk(TypedDict):
    speaker: str | None
    text: str
    start_seconds: float
    end_seconds: float


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _transcribe_one(
    audio_bytes: bytes, filename: str, mime: str
) -> list[TranscriptChunk]:
    result = _client().audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=(filename, audio_bytes, mime),
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )
    segments = getattr(result, "segments", None) or []
    out: list[TranscriptChunk] = []
    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        out.append(
            TranscriptChunk(
                speaker=None,
                text=text,
                start_seconds=float(getattr(seg, "start", 0.0)),
                end_seconds=float(getattr(seg, "end", 0.0)),
            )
        )
    return out


def _split_wav(audio_bytes: bytes, chunk_seconds: int) -> list[tuple[float, bytes]]:
    """Split a WAV byte string at frame boundaries.

    Returns a list of (offset_seconds, wav_bytes) where each wav_bytes is a
    self-contained, valid WAV file Whisper can ingest.
    """
    pieces: list[tuple[float, bytes]] = []
    src = wave.open(io.BytesIO(audio_bytes), "rb")
    try:
        framerate = src.getframerate()
        nchannels = src.getnchannels()
        sampwidth = src.getsampwidth()
        chunk_frames = int(chunk_seconds * framerate)
        offset_seconds = 0.0
        while True:
            frames = src.readframes(chunk_frames)
            if not frames:
                break
            buf = io.BytesIO()
            with wave.open(buf, "wb") as out:
                out.setnchannels(nchannels)
                out.setsampwidth(sampwidth)
                out.setframerate(framerate)
                out.writeframes(frames)
            pieces.append((offset_seconds, buf.getvalue()))
            offset_seconds += len(frames) / (framerate * nchannels * sampwidth)
    finally:
        src.close()
    return pieces


def transcribe(audio_bytes: bytes, filename: str, mime: str) -> list[TranscriptChunk]:
    """Transcribe audio with whisper-1, return per-segment chunks.

    Splits WAV files larger than 24 MB into chunks at frame boundaries and
    stitches the resulting segment timestamps back together with proper
    offsets. Non-WAV files larger than 24 MB will raise — Whisper has a
    25 MB hard limit and we don't have ffmpeg available to transcode.

    Whisper does not provide diarization; speaker is None.
    """
    size = len(audio_bytes)
    if size <= WHISPER_MAX_BYTES:
        return _transcribe_one(audio_bytes, filename, mime)

    is_wav = filename.lower().endswith(".wav") or "wav" in (mime or "").lower()
    if not is_wav:
        raise ValueError(
            f"audio is {size:,} bytes (>24 MB) and not WAV; can't safely chunk"
        )

    log.info("transcribe: chunking %s bytes WAV into ~%ds slices", size, CHUNK_SECONDS)
    pieces = _split_wav(audio_bytes, CHUNK_SECONDS)
    log.info("transcribe: %d chunks", len(pieces))

    all_segments: list[TranscriptChunk] = []
    for i, (offset, chunk_bytes) in enumerate(pieces):
        log.info(
            "transcribe: chunk %d/%d offset=%.1fs bytes=%d",
            i + 1,
            len(pieces),
            offset,
            len(chunk_bytes),
        )
        chunk_segments = _transcribe_one(chunk_bytes, filename, mime)
        for s in chunk_segments:
            s["start_seconds"] += offset
            s["end_seconds"] += offset
            all_segments.append(s)
    return all_segments
