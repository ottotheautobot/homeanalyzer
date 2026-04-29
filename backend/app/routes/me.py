from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from uuid import uuid4

from app.db.supabase import supabase
from app.deps import AuthUser, current_user
from app.services import routing
from app.services.geocode import geocode_address

router = APIRouter(tags=["me"])


class SavedLocationOut(BaseModel):
    id: str
    label: str
    address: str | None
    lat: float
    lng: float
    kind: str


class SavedLocationIn(BaseModel):
    """Client sends fully-resolved entries. Adding a new one goes through
    /me/saved-locations/geocode first to get coords, then comes back as
    part of the full array."""

    id: str
    label: str = Field(max_length=60)
    address: str | None = Field(default=None, max_length=200)
    lat: float
    lng: float
    kind: str = "other"


class MeOut(BaseModel):
    id: str
    email: str
    name: str | None
    default_zoom_url: str | None
    saved_locations: list[SavedLocationOut]


class MePatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    default_zoom_url: str | None = Field(default=None, max_length=2000)
    saved_locations: list[SavedLocationIn] | None = None


class GeocodeIn(BaseModel):
    address: str = Field(max_length=300)


class GeocodeOut(BaseModel):
    address: str
    lat: float
    lng: float


def _read_me(user_id: str, email: str) -> MeOut:
    sb = supabase()
    res = (
        sb.table("users")
        .select("id, email, name, default_zoom_url, saved_locations")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    row = res.data[0] if res.data else {"id": user_id, "email": email}
    raw_locs = row.get("saved_locations") or []
    locs = [
        SavedLocationOut(
            id=loc["id"],
            label=loc["label"],
            address=loc.get("address"),
            lat=float(loc["lat"]),
            lng=float(loc["lng"]),
            kind=loc.get("kind") or "other",
        )
        for loc in routing.iter_locations(raw_locs)
    ]
    return MeOut(
        id=row["id"],
        email=row["email"],
        name=row.get("name"),
        default_zoom_url=row.get("default_zoom_url"),
        saved_locations=locs,
    )


@router.get("/me", response_model=MeOut)
def get_me(user: AuthUser = Depends(current_user)) -> MeOut:
    return _read_me(user.id, user.email)


@router.patch("/me", response_model=MeOut)
def patch_me(
    payload: MePatch,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(current_user),
) -> MeOut:
    """Update name, default Zoom URL, and/or saved locations. Empty string
    on Zoom URL = clear it. Omitting a field = no change."""
    update: dict = {}
    if payload.name is not None:
        cleaned = payload.name.strip()
        update["name"] = cleaned or None
    if payload.default_zoom_url is not None:
        cleaned = payload.default_zoom_url.strip()
        if cleaned and not (
            cleaned.startswith("https://")
            or cleaned.startswith("http://")
            or cleaned.startswith("zoommtg:")
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Zoom URL must start with https:// or zoommtg:",
            )
        update["default_zoom_url"] = cleaned or None

    saved_locations_changed = False
    if payload.saved_locations is not None:
        # Re-validate via routing.iter_locations so a malformed entry
        # can't get persisted (e.g. lat/lng out of range).
        validated = routing.iter_locations(
            [loc.model_dump() for loc in payload.saved_locations]
        )
        update["saved_locations"] = validated
        saved_locations_changed = True

    if update:
        sb = supabase()
        sb.table("users").update(update).eq("id", user.id).execute()

    if saved_locations_changed:
        # Recompute every house's commute cache against the new saved
        # locations. Background — patch returns immediately.
        background_tasks.add_task(routing.recompute_for_user, user.id)

    return _read_me(user.id, user.email)


@router.post("/me/saved-locations/geocode", response_model=GeocodeOut)
def geocode_saved_location(
    payload: GeocodeIn, _: AuthUser = Depends(current_user)
) -> GeocodeOut:
    """Resolve a free-text address to (lat, lng) so the client can add it
    to its saved-locations list. Uses the existing Nominatim helper —
    1 req/sec rate limit, free, no key."""
    coords = geocode_address(payload.address)
    if not coords:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Couldn't find that address. Try a more specific one (street + city).",
        )
    return GeocodeOut(address=payload.address.strip(), lat=coords[0], lng=coords[1])


@router.post("/me/saved-locations/new-id")
def new_location_id(_: AuthUser = Depends(current_user)) -> dict:
    """Mint a fresh UUID for a new saved-location entry. Server-side so
    the client doesn't depend on a uuid lib for one-off id generation."""
    return {"id": str(uuid4())}
