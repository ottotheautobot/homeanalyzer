"""Browserless.io thin client — render a URL with a real Chrome
instance (stealth mode on) and return the resulting screenshot.

We use this to bypass the anti-bot blocks on Zillow/Redfin/etc. that
defeat plain httpx. Browserless runs a real browser with residential-
adjacent fingerprints, so a search-results page renders normally and
we can ship the screenshot to Haiku Vision for field extraction.

API docs: docs.browserless.io. We hit the v2 /screenshot endpoint with
the BROWSERLESS_API_TOKEN as a query param. Response is the raw image
bytes (PNG by default)."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_BROWSERLESS_BASE = "https://production-sfo.browserless.io"


def is_configured() -> bool:
    return bool(settings.browserless_api_token)


def screenshot(
    url: str,
    *,
    viewport_width: int = 1366,
    viewport_height: int = 900,
    wait_for_ms: int = 2500,
    timeout_ms: int = 30000,
) -> bytes | None:
    """Render `url` via Browserless and return PNG bytes. Returns None
    on any failure (service not configured, HTTP error, timeout) so
    the caller can degrade gracefully.

    Stealth-mode plugins are auto-applied on Browserless's standard
    /screenshot endpoint when ?stealth=true is set."""
    if not settings.browserless_api_token:
        log.info("browserless: not configured, skipping screenshot")
        return None

    try:
        with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
            r = client.post(
                f"{_BROWSERLESS_BASE}/screenshot",
                params={
                    "token": settings.browserless_api_token,
                    "stealth": "true",
                    "blockAds": "true",
                },
                json={
                    "url": url,
                    "options": {
                        "type": "png",
                        "fullPage": False,
                        "omitBackground": False,
                    },
                    "viewport": {
                        "width": viewport_width,
                        "height": viewport_height,
                        "deviceScaleFactor": 1,
                    },
                    "gotoOptions": {
                        "waitUntil": "networkidle2",
                        "timeout": timeout_ms,
                    },
                    "waitForTimeout": wait_for_ms,
                },
            )
    except Exception:
        log.exception("browserless screenshot request failed for %s", url[:120])
        return None

    if r.status_code != 200:
        log.warning(
            "browserless screenshot non-200 url=%s status=%s body=%s",
            url[:120],
            r.status_code,
            r.text[:200] if r.text else "",
        )
        return None

    body = r.content
    if not body:
        log.warning("browserless returned empty body for %s", url[:120])
        return None
    log.info(
        "browserless screenshot ok url=%s bytes=%d",
        url[:80],
        len(body),
    )
    return body
