"""Mapbox client — single vendor for forward geocoding, autocomplete,
and the directions matrix used by saved-locations commute distances.

Replaced (in v2.8) the ORS Pelias + Photon + Nominatim + Zippopotam.us
+ ORS Matrix cascade we'd accumulated to stay on free tiers. Mapbox's
free tier (100k req/mo geocoding, similar matrix budget) covers our
discovery-phase volume comfortably and the coverage of US residential
addresses is materially better than the OSM-derived alternatives.

API references:
  - v6 forward geocoding: https://docs.mapbox.com/api/search/geocoding/
  - directions matrix: https://docs.mapbox.com/api/navigation/matrix/
"""
from __future__ import annotations

import logging
from typing import Tuple

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_GEOCODE_FORWARD_URL = "https://api.mapbox.com/search/geocode/v6/forward"
_MATRIX_BASE = "https://api.mapbox.com/directions-matrix/v1/mapbox/driving"


def is_configured() -> bool:
    return bool(settings.mapbox_api_token)


# -- Geocoding -----------------------------------------------------------


def autocomplete(query: str, limit: int = 5) -> list[dict]:
    """Free-text → ranked [{address, lat, lng}, …] for the in-app
    autocomplete dropdown. Returns [] on any failure / empty response.

    `autocomplete=true` makes Mapbox return partial-match suggestions
    rather than only resolved addresses, which is what we want as the
    user types. `country=us` keeps the noise floor low."""
    if not query.strip():
        return []
    if not settings.mapbox_api_token:
        log.info("mapbox: not configured, skipping autocomplete")
        return []

    try:
        with httpx.Client(timeout=httpx.Timeout(8.0)) as client:
            r = client.get(
                _GEOCODE_FORWARD_URL,
                params={
                    "q": query.strip(),
                    "access_token": settings.mapbox_api_token,
                    "limit": min(limit, 10),
                    "country": "us",
                    "autocomplete": "true",
                    # Address types we care about for the form: full
                    # street addresses + named places (e.g. "Whole
                    # Foods, Plantation FL" can be a saved location).
                    "types": "address,street,place,locality,postcode",
                    "language": "en",
                },
            )
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.exception("mapbox autocomplete failed for %s", query[:80])
        return []

    out: list[dict] = []
    for f in data.get("features", []):
        props = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        # v6 ships a clean human-readable string in `full_address`.
        address = props.get("full_address") or props.get("place_formatted")
        if not address:
            # Fall back to assembling from context blocks if needed.
            address = props.get("name") or ""
        if not address:
            continue
        out.append(
            {"address": address, "lat": float(coords[1]), "lng": float(coords[0])}
        )
    return out


def geocode(address: str) -> Tuple[float, float] | None:
    """Resolve a single address to (lat, lng). Returns None when no
    confident match exists. Uses the same forward endpoint as
    autocomplete but with `autocomplete=false` for a stricter match."""
    if not address.strip():
        return None
    if not settings.mapbox_api_token:
        log.info("mapbox: not configured, skipping geocode")
        return None

    try:
        with httpx.Client(timeout=httpx.Timeout(8.0)) as client:
            r = client.get(
                _GEOCODE_FORWARD_URL,
                params={
                    "q": address.strip(),
                    "access_token": settings.mapbox_api_token,
                    "limit": 1,
                    "country": "us",
                    "autocomplete": "false",
                    "types": "address,street,place",
                    "language": "en",
                },
            )
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.exception("mapbox geocode failed for %s", address[:80])
        return None

    features = data.get("features") or []
    if not features:
        return None
    coords = (features[0].get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    return (float(coords[1]), float(coords[0]))


# -- Directions matrix ---------------------------------------------------


def matrix(
    sources: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
) -> tuple[list[list[float | None]], list[list[float | None]]] | None:
    """Drive-time + distance matrix from N sources to M destinations.
    Returns (durations_seconds, distances_meters) indexed
    [source_idx][destination_idx], or None on failure.

    Mapbox cap: 25 total coords per request (sources + destinations
    combined). We bail rather than chunk for now — discovery-phase
    users won't have 25+ houses or saved locations.

    Mapbox ALSO requires the matrix to have ≥2 cells (1×1 returns
    422 InvalidInput). If we'd be making a 1×1 request — common when
    a user has just one saved location — we duplicate the destination
    so the request is 1×2, then trim the result to 1×1 before
    returning."""
    if not settings.mapbox_api_token:
        return None
    if not sources or not destinations:
        return None

    # Pad to clear Mapbox's >=2-cells rule. We always have ≥1 source
    # (the house) and ≥1 destination (a saved location); the only
    # problem case is exactly 1×1.
    pad_destination = len(sources) == 1 and len(destinations) == 1
    effective_destinations = (
        destinations + [destinations[-1]] if pad_destination else destinations
    )

    coords = sources + effective_destinations
    if len(coords) > 25:
        log.warning(
            "mapbox matrix: %d coords exceeds 25 cap; skipping",
            len(coords),
        )
        return None

    coord_str = ";".join(f"{lng},{lat}" for lat, lng in coords)
    src_idxs = ";".join(str(i) for i in range(len(sources)))
    dst_idxs = ";".join(
        str(i) for i in range(len(sources), len(coords))
    )

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            r = client.get(
                f"{_MATRIX_BASE}/{coord_str}",
                params={
                    "annotations": "duration,distance",
                    "sources": src_idxs,
                    "destinations": dst_idxs,
                    "access_token": settings.mapbox_api_token,
                },
            )
        if r.status_code != 200:
            log.warning(
                "mapbox matrix non-200 status=%s body=%s",
                r.status_code,
                r.text[:300],
            )
            return None
        data = r.json()
    except Exception:
        log.exception("mapbox matrix request failed")
        return None

    if data.get("code") != "Ok":
        log.warning("mapbox matrix non-Ok: %s", data.get("code"))
        return None

    durations = data.get("durations") or []
    distances = data.get("distances") or []

    # If we padded with a duplicate destination, trim each row back to
    # the original length so the returned matrix matches what the
    # caller asked for.
    if pad_destination:
        durations = [row[:1] for row in durations]
        distances = [row[:1] for row in distances]

    return durations, distances
