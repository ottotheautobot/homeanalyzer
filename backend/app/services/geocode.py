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


_ORS_AUTOCOMPLETE_URL = "https://api.openrouteservice.org/geocode/autocomplete"
_PHOTON_URL = "https://photon.komoot.io/api/"


class GeocodeSuggestion(dict):
    """Lightweight dict with .address / .lat / .lng for the autocomplete
    JSON response. Plain dicts keep FastAPI serialization trivial."""


def autocomplete_addresses(query: str, limit: int = 5) -> list[dict]:
    """Free-text -> ranked list of {address, lat, lng} suggestions for
    the in-app autocomplete dropdown. Tries ORS Pelias first
    (OPENROUTESERVICE_API_TOKEN, much better US residential coverage
    via OpenAddresses + OSM), falls back to Photon (free, no key, OSM-
    only) if ORS isn't configured or returns nothing.

    Boundaries: ORS biased to US-only. Photon doesn't have a country
    filter equivalent that reliably scopes results, so its noise floor
    is higher when it's the fallback."""
    from app.config import settings as _settings

    q = query.strip()
    if len(q) < 3:
        return []

    out: list[dict] = []

    # Tier 1: ORS Pelias autocomplete.
    if _settings.openrouteservice_api_token:
        try:
            r = httpx.get(
                _ORS_AUTOCOMPLETE_URL,
                params={
                    "api_key": _settings.openrouteservice_api_token,
                    "text": q,
                    "size": limit,
                    "boundary.country": "US",
                },
                timeout=8.0,
            )
            r.raise_for_status()
            data = r.json()
            for f in data.get("features", []):
                geom = f.get("geometry") or {}
                coords = geom.get("coordinates") or []
                props = f.get("properties") or {}
                if len(coords) < 2:
                    continue
                lng, lat = coords[0], coords[1]
                # Pelias gives a `label` ready for display
                # ("123 Main St, Fort Lauderdale, FL, USA").
                label = props.get("label") or props.get("name")
                if not label:
                    continue
                out.append({"address": label, "lat": float(lat), "lng": float(lng)})
            if out:
                return out
        except Exception:
            log.exception("ORS autocomplete failed; falling back to Photon")

    # Tier 2: Photon (free, no key, OSM-only). Proxied so the
    # frontend hits a single endpoint regardless of provider chain.
    # Photon 403s some cloud IPs when no User-Agent is set.
    try:
        r = httpx.get(
            _PHOTON_URL,
            params={"q": q, "limit": limit},
            headers={"User-Agent": _USER_AGENT},
            timeout=8.0,
        )
        r.raise_for_status()
        data = r.json()
        for f in data.get("features", []):
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or []
            props = f.get("properties") or {}
            if len(coords) < 2:
                continue
            lng, lat = coords[0], coords[1]
            housenumber = props.get("housenumber")
            street = props.get("street")
            name = props.get("name")
            # Photon often stuffs the house number into `name` (e.g.
            # "Peters Road/# 8200 - (Plantation Colony)") when OSM
            # tagging didn't break it out into `housenumber`. Detect
            # that and prefer `name` so we don't lose the digits.
            constructed = " ".join(p for p in [housenumber, street] if p)
            if not housenumber and name and any(ch.isdigit() for ch in name):
                head = name
            elif constructed:
                head = constructed
            else:
                head = name or ""
            tail_parts = [
                props.get("city") or props.get("district"),
                props.get("state"),
                props.get("postcode"),
            ]
            tail = ", ".join(p for p in tail_parts if p)
            label = f"{head}, {tail}".strip(", ") if head else tail
            if not label:
                continue
            out.append({"address": label, "lat": float(lat), "lng": float(lng)})
        if out:
            return out
    except Exception:
        log.exception("Photon autocomplete failed")

    # Tier 3: Nominatim (the backend's existing geocoder for /save).
    # Slow (1 req/s rate-limited), but it's the most lenient on
    # US residential and named places — the same source that the user
    # sees when they submit-without-picking. Surfacing it here means
    # the autocomplete dropdown matches what the save path would
    # accept.
    try:
        global _last_call_at
        elapsed = time.monotonic() - _last_call_at
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        _last_call_at = time.monotonic()
        r = httpx.get(
            _NOMINATIM_URL,
            params={
                "q": q,
                "format": "json",
                "limit": limit,
                "addressdetails": 1,
                "countrycodes": "us",
            },
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en"},
            timeout=8.0,
        )
        r.raise_for_status()
        for item in r.json():
            display = item.get("display_name")
            if not display:
                continue
            try:
                lat = float(item["lat"])
                lng = float(item["lon"])
            except (KeyError, ValueError):
                continue
            out.append({"address": display, "lat": lat, "lng": lng})
    except Exception:
        log.exception("Nominatim autocomplete failed")

    return out


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
