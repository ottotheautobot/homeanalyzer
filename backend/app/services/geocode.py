"""Address geocoding + autocomplete — thin wrapper over app.services.mapbox.

History: pre-v2.8 this module cascaded ORS Pelias → Photon → Nominatim
+ a Zippopotam.us ZIP-city lookup + a synthesis hack to inject
house-numbered suggestions where the free indexes only had
street-level matches. All of that was in service of staying $0/mo on
free OSM-derived tools whose US residential coverage is patchy.
v2.8 collapsed it to a single Mapbox v6 Geocoding call (autocomplete
+ forward both) — clean, comprehensive, ~$0 at our scale on Mapbox's
100k/mo free tier."""
from __future__ import annotations

import logging
import re
from typing import Tuple

from app.services import mapbox

log = logging.getLogger(__name__)


# Patterns that are obvious noise — skip even calling the geocoder.
_TEST_PATTERNS = re.compile(
    r"\b(test|fake|asdf|qwer|foo|bar|baz|sample|example|dummy|placeholder|todo|tbd|n/a)\b",
    re.IGNORECASE,
)
# Repeated chars: "aaa", "1111", "abcabc"
_REPEAT_PATTERN = re.compile(r"(.)\1{4,}")


def looks_like_address(address: str) -> bool:
    """Cheap pre-filter — return False for input that's clearly not an
    address so we don't burn a Mapbox call on it. Also gates the
    backfill script's heuristic for "is this a real house entry vs a
    test row."""
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


def autocomplete_addresses(query: str, limit: int = 5) -> list[dict]:
    """Free-text → ranked list of {address, lat, lng} for the in-app
    autocomplete dropdown. Single Mapbox v6 call; empty list on any
    failure or before the user has typed enough characters."""
    q = query.strip()
    if len(q) < 3:
        return []
    return mapbox.autocomplete(q, limit=limit)


def geocode_address(address: str, timeout: float = 8.0) -> Tuple[float, float] | None:
    """Resolve a free-text address to (lat, lng). None when no
    confident match. Used at house-create time (lazy-geocode for the
    map pin) and by /me/saved-locations/geocode when a user types a
    saved location without picking from autocomplete.

    `timeout` retained for signature compatibility — Mapbox client
    sets its own internal timeout."""
    del timeout  # internal mapbox client manages timeout
    s = address.strip()
    if not looks_like_address(s):
        log.info("geocode skipped (heuristic reject) %r", s)
        return None
    return mapbox.geocode(s)
