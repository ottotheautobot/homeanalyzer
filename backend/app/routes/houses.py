import logging
import time
from datetime import datetime
from uuid import uuid4

import sentry_sdk
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["houses"])
log = logging.getLogger(__name__)


class HouseCreate(BaseModel):
    address: str
    list_price: float | None = None
    price_kind: str | None = None  # 'sale' | 'rent'
    sqft: int | None = None
    beds: float | None = None
    baths: float | None = None


class HouseOut(BaseModel):
    id: str
    tour_id: str
    address: str
    list_price: float | None
    price_kind: str | None
    sqft: int | None
    beds: float | None
    baths: float | None
    listing_url: str | None
    scheduled_at: datetime | None
    status: str
    overall_score: float | None
    overall_notes: str | None
    bot_id: str | None
    current_room: str | None
    tour_started_at: datetime | None
    audio_url: str | None
    video_url: str | None
    video_duration_seconds: float | None
    photo_url: str | None
    photo_signed_url: str | None = None
    synthesis_md: str | None
    floor_plan_json: dict | None = None
    measured_floor_plan_json: dict | None = None
    measured_floor_plan_status: str | None = None
    measured_floor_plan_error: str | None = None
    measured_floor_plan_started_at: datetime | None = None


class TranscriptOut(BaseModel):
    id: str
    house_id: str
    bot_id: str
    speaker: str | None
    text: str
    start_seconds: float
    end_seconds: float | None
    processed: bool


class ObservationOut(BaseModel):
    id: str
    house_id: str
    user_id: str | None
    room: str | None
    category: str
    content: str
    severity: str | None
    source: str
    created_at: datetime
    recall_timestamp: float | None


def assert_tour_member(tour_id: str, user_id: str) -> None:
    sb = supabase()
    res = (
        sb.table("tour_participants")
        .select("tour_id")
        .eq("tour_id", tour_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour not found")


def get_house_for_user(house_id: str, user_id: str) -> dict:
    sb = supabase()
    res = sb.table("houses").select("*").eq("id", house_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "House not found")
    house = res.data[0]
    assert_tour_member(house["tour_id"], user_id)
    return house


def _sign_photo(path: str | None) -> str | None:
    if not path:
        return None
    try:
        res = supabase().storage.from_("tour-audio").create_signed_url(path, 3600)
        return res.get("signedURL") or res.get("signedUrl")
    except Exception as e:
        log.exception("photo sign failed for %s", path)
        sentry_sdk.capture_exception(e)
        return None


def _to_house_out(row: dict) -> "HouseOut":
    return HouseOut(**row, photo_signed_url=_sign_photo(row.get("photo_url")))


@router.post(
    "/tours/{tour_id}/houses",
    response_model=HouseOut,
    status_code=status.HTTP_201_CREATED,
)
def create_house(
    tour_id: str,
    payload: HouseCreate,
    user: AuthUser = Depends(current_user),
) -> HouseOut:
    assert_tour_member(tour_id, user.id)
    sb = supabase()
    data = payload.model_dump(mode="json", exclude_none=True)
    data["tour_id"] = tour_id
    res = sb.table("houses").insert(data).execute()
    return _to_house_out(res.data[0])


@router.get("/houses", response_model=list[HouseOut])
def list_all_houses(
    user: AuthUser = Depends(current_user),
    status_eq: str | None = None,
) -> list[HouseOut]:
    """List every house across every tour the user participates in.
    Optional ?status_eq= filter (e.g. "completed") to narrow down."""
    sb = supabase()
    tp = (
        sb.table("tour_participants")
        .select("tour_id")
        .eq("user_id", user.id)
        .execute()
    )
    tour_ids = [r["tour_id"] for r in (tp.data or [])]
    if not tour_ids:
        return []
    q = sb.table("houses").select("*").in_("tour_id", tour_ids)
    if status_eq:
        q = q.eq("status", status_eq)
    res = q.order("scheduled_at", desc=False).execute()
    return [_to_house_out(h) for h in res.data or []]


class HouseMapPin(BaseModel):
    id: str
    tour_id: str
    address: str
    latitude: float
    longitude: float
    overall_score: float | None
    status: str
    photo_signed_url: str | None


class HouseMapResponse(BaseModel):
    pins: list[HouseMapPin]
    total_houses: int
    pending_geocode: int


# Hard cap on synchronous geocoding per request — Nominatim is rate-limited
# to ~1 req/s, and Vercel SSR functions time out at 10 s by default.
_MAX_SYNC_GEOCODE = 2


def _geocode_house(house_id: str, address: str) -> None:
    """Background-task entry point: geocode one house and persist the result."""
    from datetime import datetime, timezone

    from app.services.geocode import geocode_address

    coords = geocode_address(address)
    sb = supabase()
    now = datetime.now(timezone.utc).isoformat()
    if coords is not None:
        sb.table("houses").update(
            {"latitude": coords[0], "longitude": coords[1], "geocoded_at": now}
        ).eq("id", house_id).execute()
    else:
        # Mark attempted so we don't retry on every refresh.
        sb.table("houses").update({"geocoded_at": now}).eq(
            "id", house_id
        ).execute()


@router.get("/houses/map", response_model=HouseMapResponse)
def list_houses_for_map(
    background: BackgroundTasks,
    user: AuthUser = Depends(current_user),
    geocode_missing: bool = True,
) -> HouseMapResponse:
    """Return every house the user can see, with lat/lng.

    Geocoding is bounded: at most _MAX_SYNC_GEOCODE addresses are resolved
    inside the request (so SSR returns in <3 s); the rest are queued as
    BackgroundTasks and show up on the next page refresh."""
    from datetime import datetime, timezone

    from app.services.geocode import geocode_address

    sb = supabase()
    tp = (
        sb.table("tour_participants")
        .select("tour_id")
        .eq("user_id", user.id)
        .execute()
    )
    tour_ids = [r["tour_id"] for r in (tp.data or [])]
    if not tour_ids:
        return HouseMapResponse(pins=[], total_houses=0, pending_geocode=0)
    res = (
        sb.table("houses")
        .select(
            "id, tour_id, address, latitude, longitude, geocoded_at, "
            "overall_score, status, photo_signed_url"
        )
        .in_("tour_id", tour_ids)
        .execute()
    )
    rows = res.data or []
    pins: list[HouseMapPin] = []
    now = datetime.now(timezone.utc).isoformat()
    sync_budget = _MAX_SYNC_GEOCODE if geocode_missing else 0
    pending = 0
    for h in rows:
        lat = h.get("latitude")
        lng = h.get("longitude")
        # Already cached
        if lat is not None and lng is not None:
            pass
        elif (
            geocode_missing
            and h.get("address")
            # Only attempt if we haven't already tried + failed
            and not h.get("geocoded_at")
        ):
            if sync_budget > 0:
                sync_budget -= 1
                coords = geocode_address(h["address"])
                if coords is not None:
                    lat, lng = coords
                    sb.table("houses").update(
                        {
                            "latitude": lat,
                            "longitude": lng,
                            "geocoded_at": now,
                        }
                    ).eq("id", h["id"]).execute()
                else:
                    sb.table("houses").update({"geocoded_at": now}).eq(
                        "id", h["id"]
                    ).execute()
            else:
                # Past sync budget — push to background, returns next refresh.
                background.add_task(
                    _geocode_house, house_id=h["id"], address=h["address"]
                )
                pending += 1
        if lat is None or lng is None:
            continue
        pins.append(
            HouseMapPin(
                id=h["id"],
                tour_id=h["tour_id"],
                address=h["address"],
                latitude=float(lat),
                longitude=float(lng),
                overall_score=h.get("overall_score"),
                status=h.get("status") or "upcoming",
                photo_signed_url=h.get("photo_signed_url"),
            )
        )
    return HouseMapResponse(
        pins=pins, total_houses=len(rows), pending_geocode=pending
    )


@router.get("/tours/{tour_id}/houses", response_model=list[HouseOut])
def list_houses(
    tour_id: str, user: AuthUser = Depends(current_user)
) -> list[HouseOut]:
    assert_tour_member(tour_id, user.id)
    sb = supabase()
    res = (
        sb.table("houses")
        .select("*")
        .eq("tour_id", tour_id)
        .order("scheduled_at", desc=False)
        .execute()
    )
    return [_to_house_out(h) for h in res.data]


@router.get("/houses/{house_id}", response_model=HouseOut)
def get_house(house_id: str, user: AuthUser = Depends(current_user)) -> HouseOut:
    return _to_house_out(get_house_for_user(house_id, user.id))


class MediaUrls(BaseModel):
    audio_url: str | None
    video_url: str | None
    photo_url: str | None


@router.get("/houses/{house_id}/media", response_model=MediaUrls)
def get_media(
    house_id: str, user: AuthUser = Depends(current_user)
) -> MediaUrls:
    """Return signed URLs for the house's archived audio + video. URLs expire
    in 1 hour; the page refetches on next load."""
    house = get_house_for_user(house_id, user.id)
    sb = supabase()

    def _sign(path: str | None) -> str | None:
        if not path:
            return None
        try:
            res = sb.storage.from_("tour-audio").create_signed_url(path, 3600)
            return res.get("signedURL") or res.get("signedUrl")
        except Exception as e:
            log.exception("sign url failed for %s", path)
            sentry_sdk.capture_exception(e)
            return None

    return MediaUrls(
        audio_url=_sign(house.get("audio_url")),
        video_url=_sign(house.get("video_url")),
        photo_url=_sign(house.get("photo_url")),
    )


@router.post("/houses/{house_id}/photo", response_model=HouseOut)
async def upload_house_photo(
    house_id: str,
    photo: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
) -> HouseOut:
    """Upload a curb appeal photo for the house. Stored under the same
    {house_id}/ prefix as the recordings so existing per-house cleanup
    captures it on delete."""
    house = get_house_for_user(house_id, user.id)
    photo_bytes = await photo.read()
    if not photo_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty photo")

    filename = photo.filename or "photo.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "heic", "webp"):
        ext = "jpg"
    mime = photo.content_type or "image/jpeg"
    storage_path = f"{house['id']}/photo-{int(time.time())}-{uuid4().hex[:8]}.{ext}"

    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=storage_path,
        file=photo_bytes,
        file_options={"content-type": mime, "upsert": "true"},
    )
    res = (
        sb.table("houses")
        .update({"photo_url": storage_path})
        .eq("id", house_id)
        .execute()
    )
    return _to_house_out(res.data[0])


class PhotoObservationOut(BaseModel):
    observations_added: int
    photo_storage_path: str


@router.post(
    "/houses/{house_id}/photo-observation",
    response_model=PhotoObservationOut,
)
async def upload_photo_observation(
    house_id: str,
    photo: UploadFile = File(...),
    room: str | None = Form(default=None),
    user: AuthUser = Depends(current_user),
) -> PhotoObservationOut:
    """Snap a photo, get vision-extracted observations on the house brief.
    Distinct from POST /houses/{id}/photo (which sets the curb-appeal photo).

    Stored under {house_id}/notes/ — covered by the same delete cleanup."""
    house = get_house_for_user(house_id, user.id)
    photo_bytes = await photo.read()
    if not photo_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty photo")
    if len(photo_bytes) > 12 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Photo too large"
        )

    filename = photo.filename or "note.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "heic", "webp"):
        ext = "jpg"
    mime = photo.content_type or "image/jpeg"
    storage_path = (
        f"{house['id']}/notes/photo-{int(time.time())}-{uuid4().hex[:8]}.{ext}"
    )

    sb = supabase()
    sb.storage.from_("tour-audio").upload(
        path=storage_path,
        file=photo_bytes,
        file_options={"content-type": mime, "upsert": "true"},
    )

    from app.llm.vision import analyze_single_image

    room_hint = room.strip().lower() if room and room.strip() else None
    obs = analyze_single_image(photo_bytes, room_hint=room_hint)
    if obs:
        rows = [
            {
                "house_id": house["id"],
                "user_id": user.id,
                "room": o.get("room"),
                "category": o.get("category", "note"),
                "content": o["content"],
                "severity": o.get("severity"),
                "source": "user_photo_analysis",
            }
            for o in obs
            if o.get("content")
        ]
        if rows:
            sb.table("observations").insert(rows).execute()
    return PhotoObservationOut(
        observations_added=len(obs),
        photo_storage_path=storage_path,
    )


@router.delete("/houses/{house_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_house(
    house_id: str, user: AuthUser = Depends(current_user)
) -> Response:
    """Delete a house and all associated data: observations, transcripts
    (cascaded by FK), plus storage files under {house_id}/. Stops any
    active bot first."""
    house = get_house_for_user(house_id, user.id)
    sb = supabase()

    if house.get("bot_id"):
        from app.providers.meetingbaas import get_meeting_provider

        try:
            await get_meeting_provider().stop_bot(house["bot_id"])
        except Exception as e:
            log.exception("stop_bot failed during delete for house %s", house_id)
            sentry_sdk.capture_exception(e)

    try:
        files = sb.storage.from_("tour-audio").list(house_id) or []
        paths = [f"{house_id}/{f['name']}" for f in files if f.get("name")]
        if paths:
            sb.storage.from_("tour-audio").remove(paths)
    except Exception as e:
        log.exception("storage cleanup failed for house %s", house_id)
        sentry_sdk.capture_exception(e)

    sb.table("houses").delete().eq("id", house_id).execute()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/houses/{house_id}/transcripts", response_model=list[TranscriptOut]
)
def list_transcripts(
    house_id: str, user: AuthUser = Depends(current_user)
) -> list[TranscriptOut]:
    get_house_for_user(house_id, user.id)
    sb = supabase()
    res = (
        sb.table("transcripts")
        .select("*")
        .eq("house_id", house_id)
        .order("start_seconds", desc=False)
        .execute()
    )
    return [TranscriptOut(**t) for t in res.data]


@router.get(
    "/houses/{house_id}/observations", response_model=list[ObservationOut]
)
def list_observations(
    house_id: str, user: AuthUser = Depends(current_user)
) -> list[ObservationOut]:
    get_house_for_user(house_id, user.id)
    sb = supabase()
    res = (
        sb.table("observations")
        .select("*")
        .eq("house_id", house_id)
        .order("created_at", desc=False)
        .execute()
    )
    return [ObservationOut(**o) for o in res.data]


@router.post("/houses/{house_id}/regenerate-floorplan", response_model=HouseOut)
def regenerate_floor_plan(
    house_id: str, user: AuthUser = Depends(current_user)
) -> HouseOut:
    """Re-run the schematic floor-plan generator for a completed house.
    Useful for backfilling existing tours or iterating on the prompt."""
    house = get_house_for_user(house_id, user.id)
    sb = supabase()

    transcripts = (
        sb.table("transcripts")
        .select("*")
        .eq("house_id", house_id)
        .order("start_seconds", desc=False)
        .execute()
    )
    observations = (
        sb.table("observations")
        .select("*")
        .eq("house_id", house_id)
        .order("created_at", desc=False)
        .execute()
    )

    from app.llm.floor_plan import generate_floor_plan

    plan = generate_floor_plan(
        transcripts.data or [],
        observations.data or [],
        house.get("synthesis_md"),
    )
    res = (
        sb.table("houses")
        .update({"floor_plan_json": plan})
        .eq("id", house_id)
        .execute()
    )
    return _to_house_out(res.data[0])
