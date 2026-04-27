import logging
from typing import Any

import httpx
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import settings
from app.providers.meeting import (
    CompletionPayload,
    MeetingProvider,
    StatusEvent,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.meetingbaas.com"
AUTH_HEADER = "x-meeting-baas-api-key"


class MeetingBaasProvider(MeetingProvider):
    async def start_bot(
        self,
        meeting_url: str,
        bot_name: str,
        webhook_url: str,
        streaming_input_url: str,
        extra: dict | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "reserved": False,
            "recording_mode": "speaker_view",
            "speech_to_text": None,
            # Tight timeouts — bots that can't get admitted within 90s should
            # exit, not idle for 10 minutes burning tokens.
            "automatic_leave": {
                "waiting_room_timeout": 90,
                "noone_joined_timeout": 90,
                # Floor per v1 docs is ~300s. Default 600s = up to 10 min of
                # billed silence at the tail of every tour if we don't end
                # cleanly. 300s caps that worst case.
                "silence_timeout": 300,
            },
            "webhook_url": webhook_url,
        }
        if settings.meetingbaas_enable_streaming:
            # MB v1 docs are ambiguous on direction; reference impl
            # (Meeting-BaaS/realtime-meeting-transcription) uses
            # `streaming.output` to receive meeting audio, not `streaming.input`.
            # Our previous .input config produced 0 frames — try .output.
            body["streaming"] = {
                "audio_frequency": "16khz",
                "input": None,
                "output": streaming_input_url,
            }
        if settings.zoom_sdk_id and settings.zoom_sdk_secret:
            body["zoom_sdk_id"] = settings.zoom_sdk_id
            body["zoom_sdk_pwd"] = settings.zoom_sdk_secret
        if extra:
            body["extra"] = extra

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{API_BASE}/bots/",
                headers={AUTH_HEADER: settings.meetingbaas_api_key},
                json=body,
            )
        if r.status_code >= 400:
            log.error("meetingbaas start_bot failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        data = r.json()
        bot_id = data.get("bot_id") or data.get("data", {}).get("bot_id")
        if not bot_id:
            raise RuntimeError(f"meetingbaas response missing bot_id: {data}")
        return str(bot_id)

    async def stop_bot(self, bot_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(
                f"{API_BASE}/bots/{bot_id}",
                headers={AUTH_HEADER: settings.meetingbaas_api_key},
            )
        if r.status_code in (200, 204, 404):
            return
        log.error("meetingbaas stop_bot failed: %s %s", r.status_code, r.text)
        r.raise_for_status()

    async def get_bot(self, bot_id: str) -> CompletionPayload | None:
        """GET /bots/meeting_data?bot_id=<id> — returns recording URLs +
        bot metadata + transcripts. URLs are presigned S3 with a 4h TTL.

        Response shape (verified on v1):
            {
              "bot_data": {"bot": {...metadata...}, "transcripts": [...]},
              "mp4": "https://...s3...mp4?...",
              "audio": "https://...s3...wav?...",
              "duration": float
            }

        Returns None if MB has no recording (404, purged, bot never finished).
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{API_BASE}/bots/meeting_data",
                params={"bot_id": bot_id},
                headers={AUTH_HEADER: settings.meetingbaas_api_key},
            )
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            log.error(
                "meetingbaas get_bot failed: %s %s", r.status_code, r.text[:300]
            )
            r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict):
            log.warning("get_bot %s returned non-dict body: %s", bot_id, type(body))
            return None
        audio = body.get("audio") or body.get("audio_url")
        video = body.get("mp4") or body.get("video_url") or body.get("mp4_url")
        # Transcripts come back inline (not as a URL) in the meeting_data
        # response — leave transcript_url None and let our Whisper pipeline
        # generate transcripts from audio.
        if not (audio or video):
            log.warning(
                "get_bot for %s returned no recording URLs; keys=%s",
                bot_id,
                list(body.keys()),
            )
            return None
        return CompletionPayload(
            bot_id=str(bot_id),
            duration_seconds=body.get("duration"),
            audio_url=audio,
            video_url=video,
            transcript_url=None,
        )

    def verify_webhook_signature(self, headers: dict, body: bytes) -> bool:
        if not settings.meetingbaas_webhook_secret:
            log.warning("MEETINGBAAS_WEBHOOK_SECRET not set; rejecting webhook")
            return False
        wh = Webhook(settings.meetingbaas_webhook_secret)
        norm = {k.lower(): v for k, v in headers.items()}
        try:
            wh.verify(body, norm)
            return True
        except WebhookVerificationError as e:
            log.warning("svix verification failed: %s", e)
            return False

    def parse_status_webhook(self, payload: dict) -> StatusEvent | None:
        event = payload.get("event")
        data = payload.get("data") or {}
        bot_id = data.get("bot_id")
        if not bot_id:
            return None
        if event == "bot.status_change":
            code = (data.get("status") or {}).get("code", "")
            return StatusEvent(bot_id=str(bot_id), code=code, raw=data)
        if event in ("bot.completed", "bot.failed"):
            return StatusEvent(bot_id=str(bot_id), code=event, raw=data)
        return None

    def parse_completion_webhook(self, payload: dict) -> CompletionPayload | None:
        if payload.get("event") not in ("bot.completed", "complete"):
            return None
        data = payload.get("data") or {}
        bot_id = data.get("bot_id")
        if not bot_id:
            return None
        return CompletionPayload(
            bot_id=str(bot_id),
            duration_seconds=data.get("duration_seconds"),
            audio_url=data.get("audio") or data.get("audio_url"),
            video_url=data.get("mp4") or data.get("video_url"),
            transcript_url=data.get("transcription") or data.get("transcript_url"),
        )


_provider: MeetingProvider | None = None


def get_meeting_provider() -> MeetingProvider:
    global _provider
    if _provider is None:
        _provider = MeetingBaasProvider()
    return _provider
