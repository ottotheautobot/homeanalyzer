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
            "automatic_leave": {"waiting_room_timeout": 600, "noone_joined_timeout": 600},
            "streaming": {
                "audio_frequency": "16khz",
                "input": streaming_input_url,
                "output": None,
            },
            "webhook_url": webhook_url,
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
