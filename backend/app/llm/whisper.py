from functools import lru_cache
from typing import TypedDict

from openai import OpenAI

from app.config import settings

WHISPER_MODEL = "whisper-1"


class TranscriptChunk(TypedDict):
    speaker: str | None
    text: str
    start_seconds: float
    end_seconds: float


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def transcribe(audio_bytes: bytes, filename: str, mime: str) -> list[TranscriptChunk]:
    """Transcribe audio with whisper-1, return per-segment chunks.

    Whisper does not provide diarization in this phase; speaker is None.
    Diarization arrives in Hours 8–14 via Meeting BaaS.
    """
    result = _client().audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=(filename, audio_bytes, mime),
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )

    segments = getattr(result, "segments", None) or []
    chunks: list[TranscriptChunk] = []
    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        chunks.append(
            TranscriptChunk(
                speaker=None,
                text=text,
                start_seconds=float(getattr(seg, "start", 0.0)),
                end_seconds=float(getattr(seg, "end", 0.0)),
            )
        )
    return chunks
