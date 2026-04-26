from abc import ABC, abstractmethod
from typing import TypedDict


class RecordingUrls(TypedDict, total=False):
    audio_url: str | None
    video_url: str | None
    transcript_url: str | None


class CompletionPayload(TypedDict):
    bot_id: str
    duration_seconds: float | None
    audio_url: str | None
    video_url: str | None
    transcript_url: str | None


class StatusEvent(TypedDict):
    bot_id: str
    code: str
    raw: dict


class MeetingProvider(ABC):
    """Vendor-agnostic interface for meeting bots.

    The brief locks Meeting BaaS as the v1 implementation. Recall is the
    intended v2 swap once a business email is available; new vendor logic
    must stay inside a concrete subclass and never leak into routes/handlers.
    """

    @abstractmethod
    async def start_bot(
        self,
        meeting_url: str,
        bot_name: str,
        webhook_url: str,
        streaming_input_url: str,
        extra: dict | None = None,
    ) -> str:
        """Dispatch a bot to a meeting. Returns the provider's bot_id."""

    @abstractmethod
    async def stop_bot(self, bot_id: str) -> None:
        """Remove the bot from the meeting. Idempotent on already-stopped bots."""

    @abstractmethod
    def verify_webhook_signature(self, headers: dict, body: bytes) -> bool:
        """Return True if `body` is signed by our webhook secret."""

    @abstractmethod
    def parse_status_webhook(self, payload: dict) -> StatusEvent | None:
        """Normalize a status/lifecycle webhook to a common shape.

        Returns None for events we don't care about.
        """

    @abstractmethod
    def parse_completion_webhook(self, payload: dict) -> CompletionPayload | None:
        """Normalize a terminal completion webhook with recording URLs.

        Returns None if this isn't a completion event.
        """
