"""Zoom Server-to-Server OAuth client for ending meetings programmatically.

Used by /houses/{id}/end_tour so the Zoom call closes for everyone instead
of staying open until the host manually leaves. Requires a separate Zoom
Marketplace app of type "Server-to-Server OAuth" with the
`meeting:write:meeting:admin` scope. Credentials live in env vars
ZOOM_S2S_{ACCOUNT_ID,CLIENT_ID,CLIENT_SECRET}.

Token cache is process-local. Zoom S2S tokens last 1h; we refresh ~5 min
early. Single-process backend, low call volume → no Redis needed.
"""

import logging
import re
import time
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_TOKEN_URL = "https://zoom.us/oauth/token"
_API_BASE = "https://api.zoom.us/v2"
_REFRESH_LEEWAY_SECONDS = 300  # refresh 5 min before expiry

_cached_token: Optional[str] = None
_cached_expiry: float = 0.0


def is_configured() -> bool:
    return bool(
        settings.zoom_s2s_account_id
        and settings.zoom_s2s_client_id
        and settings.zoom_s2s_client_secret
    )


def _extract_meeting_id(zoom_url: str) -> Optional[str]:
    """Pull the numeric meeting ID out of a join URL like
    https://us02web.zoom.us/j/1234567890?pwd=... — returns None for
    vanity PMR URLs (/my/<name>) since those need a separate PMI lookup
    we don't currently do."""
    m = re.search(r"/j/(\d{9,12})", zoom_url)
    return m.group(1) if m else None


async def _get_token(client: httpx.AsyncClient) -> str:
    global _cached_token, _cached_expiry
    now = time.time()
    if _cached_token and now < _cached_expiry - _REFRESH_LEEWAY_SECONDS:
        return _cached_token

    resp = await client.post(
        _TOKEN_URL,
        params={
            "grant_type": "account_credentials",
            "account_id": settings.zoom_s2s_account_id,
        },
        auth=(settings.zoom_s2s_client_id, settings.zoom_s2s_client_secret),
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    _cached_token = token
    _cached_expiry = now + expires_in
    return token


async def end_meeting(zoom_url: str) -> bool:
    """Best-effort: end the Zoom meeting referenced by `zoom_url`. Returns
    True on 204, False on any failure (URL not parseable, creds missing,
    Zoom 4xx/5xx, host not in meeting, etc.). Caller should NOT raise on
    False — ending the bot is the primary goal; ending the meeting is a
    nice-to-have layered on top."""
    if not is_configured():
        log.info("zoom S2S not configured; skipping end_meeting")
        return False

    meeting_id = _extract_meeting_id(zoom_url)
    if not meeting_id:
        log.warning(
            "zoom end_meeting: could not parse meeting id from url=%s "
            "(vanity /my/ URLs need PMI lookup, not implemented)",
            zoom_url,
        )
        return False

    async with httpx.AsyncClient() as client:
        try:
            token = await _get_token(client)
        except Exception:
            log.exception("zoom S2S token fetch failed")
            return False

        try:
            resp = await client.put(
                f"{_API_BASE}/meetings/{meeting_id}/status",
                headers={"Authorization": f"Bearer {token}"},
                json={"action": "end"},
                timeout=10.0,
            )
        except Exception:
            log.exception("zoom end_meeting request failed")
            return False

    if resp.status_code == 204:
        log.info("zoom end_meeting ok: meeting_id=%s", meeting_id)
        return True
    # 3001 = meeting not found, 3000 = meeting not started, etc. — all
    # benign in our flow (host already left, etc.).
    log.warning(
        "zoom end_meeting non-204: meeting_id=%s status=%s body=%s",
        meeting_id,
        resp.status_code,
        resp.text[:200],
    )
    return False
