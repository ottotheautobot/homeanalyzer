"""Address -> (lat, lng) via Nominatim (OpenStreetMap). Free, no key,
rate-limited to ~1 req/s. We cache results on the houses row.

Nominatim's usage policy requires a real User-Agent and asks not to bulk-
geocode in tight loops; both are honored here. For a personal app this is
plenty."""

from __future__ import annotations

import logging
import time
from typing import Tuple

import httpx

log = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "HomeAnalyzer/1 (https://github.com/ottotheautobot/homeanalyzer)"

# Process-local rate limiter: ensure we don't dispatch < 1 sec apart.
_last_call_at = 0.0


def geocode_address(address: str, timeout: float = 8.0) -> Tuple[float, float] | None:
    """Best-effort geocode. Returns None on any failure."""
    global _last_call_at
    if not address or len(address.strip()) < 4:
        return None

    elapsed = time.monotonic() - _last_call_at
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _last_call_at = time.monotonic()

    try:
        r = httpx.get(
            _NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            log.info("geocode no result for %r", address)
            return None
        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        log.info("geocode %r -> (%.5f, %.5f)", address, lat, lon)
        return (lat, lon)
    except Exception:
        log.exception("geocode failed for %r", address)
        return None
