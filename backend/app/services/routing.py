"""Distances + commute times from candidate houses to a user's saved
locations (work, school, gym, etc.).

Two-tier strategy, tried in order:
  1. **Mapbox Directions Matrix** — when MAPBOX_API_TOKEN is set.
     Free tier covers our discovery-phase volume; real drive time
     + distance.
  2. **Haversine** — always-available fallback. As-the-crow-flies
     miles, no drive time. Good enough to answer "is this even close
     to my office?" 80% of the time.

(v2.8 dropped OpenRouteService entirely — Mapbox now handles both
geocoding and routing, so we shed one vendor + one env var.)

Cache lives on `houses.commute_distances` JSONB. Invalidated when:
  - the user's saved_locations array changes (recompute all that user's
    houses)
  - a house's lat/lng changes (recompute that house only)

The compute step is run as a FastAPI BackgroundTask off the PATCH that
mutates either side, so writes are still snappy."""
from __future__ import annotations

import logging
import math
from typing import Iterable, TypedDict

from app.db.supabase import supabase
from app.services import mapbox

log = logging.getLogger(__name__)

_METERS_PER_MILE = 1609.344


class SavedLocation(TypedDict, total=False):
    id: str
    label: str
    address: str
    lat: float
    lng: float
    kind: str  # "work" | "school" | "gym" | "family" | "other"


class CommuteEntry(TypedDict, total=False):
    miles: float
    minutes: float | None  # None when fell back to haversine
    mode: str  # "driving" | "haversine"


def _haversine_miles(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    R_MILES = 3958.7613
    p1 = math.radians(a_lat)
    p2 = math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dlam = math.radians(b_lng - a_lng)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))
    return R_MILES * c


# Mapbox matrix moved to services/mapbox.py; this module just calls
# mapbox.matrix() and falls back to haversine when needed.


def compute_distances_for_house(
    house_lat: float,
    house_lng: float,
    saved_locations: list[SavedLocation],
) -> dict[str, CommuteEntry]:
    """Single-house version: returns a {saved_location_id: CommuteEntry}
    map. Uses Mapbox if configured, falls back to haversine otherwise."""
    out: dict[str, CommuteEntry] = {}
    if not saved_locations:
        return out

    locs_with_coords = [
        s for s in saved_locations if s.get("lat") is not None and s.get("lng") is not None
    ]
    if not locs_with_coords:
        return out

    durations: list[list[float | None]] | None = None
    distances: list[list[float | None]] | None = None
    house_origin = [(house_lat, house_lng)]
    saved_dests = [(s["lat"], s["lng"]) for s in locs_with_coords]

    # Try Mapbox first (real drive time/distance); haversine fallback
    # below if Mapbox is unconfigured or the request fails.
    result = mapbox.matrix(sources=house_origin, destinations=saved_dests)
    if result is not None:
        durations, distances = result

    for i, loc in enumerate(locs_with_coords):
        if durations is not None and distances is not None:
            secs = durations[0][i]
            meters = distances[0][i]
            if secs is not None and meters is not None:
                out[loc["id"]] = CommuteEntry(
                    miles=round(meters / _METERS_PER_MILE, 1),
                    minutes=round(secs / 60.0, 0),
                    mode="driving",
                )
                continue
        # Haversine fallback (or no Mapbox configured).
        miles = _haversine_miles(house_lat, house_lng, loc["lat"], loc["lng"])
        out[loc["id"]] = CommuteEntry(
            miles=round(miles, 1),
            minutes=None,
            mode="haversine",
        )
    return out


def recompute_for_user(user_id: str) -> int:
    """Recompute commute_distances for every geocoded, completed-or-toured
    house owned by user_id. Returns the number of houses updated.

    Called from a BackgroundTask off PATCH /me when saved_locations
    changes."""
    sb = supabase()
    user_res = (
        sb.table("users")
        .select("saved_locations")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    saved = (user_res.data[0] if user_res.data else {}).get("saved_locations") or []

    # Pull every house in tours owned by this user that has coords.
    tours_res = sb.table("tours").select("id").eq("owner_user_id", user_id).execute()
    tour_ids = [t["id"] for t in (tours_res.data or [])]
    if not tour_ids:
        return 0

    houses_res = (
        sb.table("houses")
        .select("id, latitude, longitude")
        .in_("tour_id", tour_ids)
        .not_.is_("latitude", "null")
        .not_.is_("longitude", "null")
        .execute()
    )
    houses = houses_res.data or []
    if not houses:
        return 0

    updated = 0
    for h in houses:
        try:
            distances = compute_distances_for_house(
                house_lat=float(h["latitude"]),
                house_lng=float(h["longitude"]),
                saved_locations=saved,
            )
            sb.table("houses").update(
                {"commute_distances": distances or None}
            ).eq("id", h["id"]).execute()
            updated += 1
        except Exception:
            log.exception("commute recompute failed for house %s", h["id"])
    log.info(
        "commute recompute for user=%s: %d houses updated against %d saved locations",
        user_id,
        updated,
        len(saved),
    )
    return updated


def recompute_for_house(house_id: str, user_id: str) -> bool:
    """Recompute one house's commute_distances after its geocode changed.
    Idempotent."""
    sb = supabase()
    house_res = (
        sb.table("houses")
        .select("id, latitude, longitude, tour_id")
        .eq("id", house_id)
        .limit(1)
        .execute()
    )
    if not house_res.data:
        return False
    h = house_res.data[0]
    if h.get("latitude") is None or h.get("longitude") is None:
        return False

    user_res = (
        sb.table("users")
        .select("saved_locations")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    saved = (user_res.data[0] if user_res.data else {}).get("saved_locations") or []

    distances = compute_distances_for_house(
        house_lat=float(h["latitude"]),
        house_lng=float(h["longitude"]),
        saved_locations=saved,
    )
    sb.table("houses").update(
        {"commute_distances": distances or None}
    ).eq("id", house_id).execute()
    return True


def iter_locations(saved: Iterable[dict]) -> list[SavedLocation]:
    """Validate + normalize input from the client. Drops entries that
    don't have id/label/lat/lng. Truncates label to 60 chars."""
    out: list[SavedLocation] = []
    for raw in saved:
        if not isinstance(raw, dict):
            continue
        sid = raw.get("id")
        label = raw.get("label")
        lat = raw.get("lat")
        lng = raw.get("lng")
        if not (sid and label and lat is not None and lng is not None):
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
            continue
        kind = raw.get("kind") or "other"
        if kind not in ("work", "school", "gym", "family", "other"):
            kind = "other"
        out.append(
            SavedLocation(
                id=str(sid),
                label=str(label)[:60],
                address=str(raw.get("address") or "")[:200] or None,
                lat=lat_f,
                lng=lng_f,
                kind=kind,
            )
        )
    return out
