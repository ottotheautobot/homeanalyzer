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

# Strip these street-type abbreviations / suffix words when comparing
# the matched street against the user's query — "Cir" vs "Circle",
# "St" vs "Street", etc. shouldn't sink a synthesis decision.
_STREET_TYPES = re.compile(
    r"\b("
    r"st(reet)?|ave(nue)?|blvd|boulevard|rd|road|dr(ive)?|ln|lane|"
    r"ct|court|cir(cle)?|way|pl(ace)?|ter(race)?|pkwy|parkway|"
    r"hwy|highway|trl|trail|aly|alley|sq(uare)?|loop|crk|creek"
    r")\b\.?",
    re.IGNORECASE,
)

# House-number prefix at the start of a query: "310 Aiken Hunt Cir...".
_HOUSE_NUMBER_PREFIX = re.compile(r"^\s*(\d{1,6})\s+(\S.*)")

# 5-digit ZIP at the start, end, or after the last comma in an address.
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

# Process-local cache for ZIP→city/state lookups so repeated synthesis
# calls for the same ZIP don't burn the rate limit.
_ZIP_CACHE: dict[str, tuple[str, str] | None] = {}


def _city_state_for_zip(zip_code: str) -> tuple[str, str] | None:
    """Resolve a US ZIP to (city, state-abbr) via api.zippopotam.us.
    Free, no key, ~50ms. None on any failure. Cached per process so a
    typing user doesn't re-hit on every keystroke."""
    if zip_code in _ZIP_CACHE:
        return _ZIP_CACHE[zip_code]
    try:
        r = httpx.get(
            f"https://api.zippopotam.us/us/{zip_code}",
            timeout=4.0,
        )
        if r.status_code != 200:
            _ZIP_CACHE[zip_code] = None
            return None
        data = r.json()
        place = (data.get("places") or [{}])[0]
        city = place.get("place name")
        state = place.get("state abbreviation")
        if city and state:
            _ZIP_CACHE[zip_code] = (city, state)
            return (city, state)
    except Exception:
        log.exception("zippopotam lookup failed for %s", zip_code)
    _ZIP_CACHE[zip_code] = None
    return None


def _normalize_street_words(s: str) -> set[str]:
    """Lowercase + drop street-type abbreviations + extract significant
    word tokens (>=3 chars) for fuzzy "is this the same street" check."""
    s = s.lower()
    s = _STREET_TYPES.sub(" ", s)
    return {w for w in re.findall(r"[a-z]+", s) if len(w) >= 3}


def _maybe_synthesize_house_addresses(
    query: str, results: list[dict]
) -> list[dict]:
    """When the user typed a leading house number but every tier only
    found the street, prepend the number to the matched address as a
    "best guess" suggestion.

    Why: free address indexes (Pelias' OpenAddresses, Photon's OSM,
    Nominatim's OSM) have spotty US house-number coverage outside
    major cities. The user types "310 Aiken Hunt Cir 29223", we get
    back "Aiken Hunt Circle, SC, 29223" with no "310" — the user is
    stuck. Synthesizing "310 Aiken Hunt Circle, SC, 29223" gives
    them something to pick; the downstream auto-fill (Apify Realtor
    /Zillow) confirms with the canonical address.

    Safety: only synthesize when at least one significant word from
    the matched street appears in the user's query. So a "310 Smith"
    query that returned "Aiken Hunt Circle" wouldn't get a misleading
    "310 Aiken Hunt Circle" suggestion."""
    m = _HOUSE_NUMBER_PREFIX.match(query)
    if not m:
        return results
    house_num = m.group(1)
    rest_query_words = _normalize_street_words(m.group(2))
    if not rest_query_words:
        return results

    synthesized: list[dict] = []
    seen = {r["address"].lstrip().lower() for r in results}

    for r in results:
        addr = r["address"]
        first_token = addr.lstrip().split(",")[0].strip().split()[:1]
        # Skip if the matched address already starts with a house number.
        if first_token and first_token[0].isdigit():
            continue
        # Verify the street name overlaps with the user's query — guards
        # against synthesizing "310 Random Street" for an unrelated match.
        street_part = addr.split(",")[0]
        match_words = _normalize_street_words(street_part)
        if not (match_words & rest_query_words):
            continue
        # Apify Realtor needs a city for a precise match. If we have a
        # ZIP (in either the user's query or the match), look up the
        # ZIP's primary city and rebuild the address as
        # `<num> <street>, <city>, <state> <zip>`. Otherwise fall back
        # to just prepending the house number to the matched address.
        zip_match = _ZIP_RE.search(query) or _ZIP_RE.search(addr)
        cs = _city_state_for_zip(zip_match.group(1)) if zip_match else None
        if cs:
            street_only = addr.split(",")[0].strip()
            city, state_abbr = cs
            synth_addr = (
                f"{house_num} {street_only}, {city}, {state_abbr} {zip_match.group(1)}"
            )
        else:
            synth_addr = f"{house_num} {addr}"
        if synth_addr.lstrip().lower() in seen:
            continue
        synthesized.append(
            {"address": synth_addr, "lat": r["lat"], "lng": r["lng"]}
        )
        seen.add(synth_addr.lstrip().lower())

    if not synthesized:
        return results
    # Suppress synthesis when an existing result already has BOTH the
    # right house number AND street-name overlap with the query (e.g.,
    # Pelias returned "8200 Peters Rd, Plantation FL"). Don't suppress
    # when the existing numbered matches are unrelated streets that
    # happen to share the house number (e.g., "310 Pasaje Los…").
    for r in results:
        first_word = r["address"].lstrip().split(",")[0].strip().split()
        if not first_word or not first_word[0].isdigit():
            continue
        if first_word[0] != house_num:
            continue
        existing_street_words = _normalize_street_words(
            r["address"].split(",")[0]
        )
        if existing_street_words & rest_query_words:
            return results
    return synthesized + results


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
                return _maybe_synthesize_house_addresses(query, out)
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
            name = props.get("name") or ""
            # Photon often stuffs the house number into `name` (e.g.
            # "Peters Road/# 8200 - (Plantation Colony)") when OSM
            # tagging didn't break it out into `housenumber`. Pull
            # the digits and reformat as "8200 Peters Road" so the
            # dropdown shows something readable.
            if not housenumber and name and street:
                m = re.search(r"#\s*(\d{1,6})\b", name) or re.search(
                    r"\b(\d{1,6})\b", name
                )
                if m:
                    housenumber = m.group(1)
            constructed = " ".join(p for p in [housenumber, street] if p)
            if constructed:
                head = constructed
            elif name:
                # Last resort: clean up the OSM name by stripping the
                # "/# 1234" notation and trailing parenthetical noise.
                cleaned = re.sub(r"\s*/\s*#?\s*\d+\s*", " ", name)
                cleaned = re.sub(r"\s*[-—]\s*\([^)]*\)\s*$", "", cleaned)
                head = cleaned.strip()
            else:
                head = ""
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
            return _maybe_synthesize_house_addresses(query, out)
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

    return _maybe_synthesize_house_addresses(query, out)


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
