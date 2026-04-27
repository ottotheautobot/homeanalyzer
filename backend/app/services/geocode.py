"""Address -> (lat, lng) via Nominatim (OpenStreetMap). Free, no key,
rate-limited to ~1 req/s. We cache results on the houses row.

Nominatim's usage policy requires a real User-Agent and asks not to bulk-
geocode in tight loops; both are honored here. For a personal app this is
plenty.

Two layers of "is this a real address" validation:
  1. Pre-call heuristic — skip Nominatim entirely for input that doesn't
     look like an address (no digit, too short, common test patterns).
  2. Post-call response check — require Nominatim's structured address
     to include a house_number + road + (city|town|village|hamlet|county)
     OR a high importance score. This filters out cases where Nominatim
     returns a "nearest match" guess for a fake address (e.g. the
     hotel down the street from a fictional house number).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Tuple

import httpx

log = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "HomeAnalyzer/1 (https://github.com/ottotheautobot/homeanalyzer)"

# Process-local rate limiter: ensure we don't dispatch < 1 sec apart.
_last_call_at = 0.0

# Patterns that are obvious noise — skip Nominatim entirely.
_TEST_PATTERNS = re.compile(
    r"\b(test|fake|asdf|qwer|foo|bar|baz|sample|example|dummy|placeholder|todo|tbd|n/a)\b",
    re.IGNORECASE,
)
# Repeated chars: "aaa", "1111", "abcabc"
_REPEAT_PATTERN = re.compile(r"(.)\1{4,}")


def looks_like_address(address: str) -> bool:
    """Cheap pre-filter — return False for input that's clearly not an
    address so we don't burn a Nominatim call on it."""
    s = address.strip()
    if len(s) < 8:
        return False
    if not any(ch.isdigit() for ch in s):
        return False  # real addresses have a street number
    if len(s.split()) < 2:
        return False  # at least street number + something else
    if _TEST_PATTERNS.search(s):
        return False
    if _REPEAT_PATTERN.search(s):
        return False
    return True


# Keys in Nominatim's `address` block that count as a "city-level" match.
# Any one is enough — coverage varies by country/region.
_CITY_KEYS = ("city", "town", "village", "hamlet", "municipality", "suburb")


def _is_precise_match(item: dict) -> bool:
    """Nominatim returned something — does it look like an actual house
    address rather than a fuzzy nearest-neighbor guess?"""
    addr = item.get("address") or {}
    has_number = bool(addr.get("house_number"))
    has_road = bool(addr.get("road") or addr.get("pedestrian"))
    has_city = any(addr.get(k) for k in _CITY_KEYS)
    importance = float(item.get("importance") or 0.0)

    # Path A: structured address looks complete (house# + road + locality)
    if has_number and has_road and has_city:
        return True
    # Path B: not a full house match but high-importance place (e.g. a
    # well-known building or estate that doesn't have a house number).
    if importance >= 0.5 and has_road and has_city:
        return True
    return False


def geocode_address(address: str, timeout: float = 8.0) -> Tuple[float, float] | None:
    """Best-effort geocode. Returns None on any failure or low-confidence
    match. See module docstring for what gets filtered."""
    global _last_call_at
    if not address:
        return None
    s = address.strip()
    if not looks_like_address(s):
        log.info("geocode skipped (heuristic reject) %r", s)
        return None

    elapsed = time.monotonic() - _last_call_at
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _last_call_at = time.monotonic()

    try:
        r = httpx.get(
            _NOMINATIM_URL,
            params={
                "q": s,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
            },
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            log.info("geocode no result for %r", s)
            return None
        item = data[0]
        if not _is_precise_match(item):
            log.info(
                "geocode imprecise match rejected %r -> %s (imp=%.3f)",
                s,
                item.get("display_name", "")[:80],
                float(item.get("importance") or 0),
            )
            return None
        lat = float(item["lat"])
        lon = float(item["lon"])
        log.info("geocode %r -> (%.5f, %.5f)", s, lat, lon)
        return (lat, lon)
    except Exception:
        log.exception("geocode failed for %r", s)
        return None
