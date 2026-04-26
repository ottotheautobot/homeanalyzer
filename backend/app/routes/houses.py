import logging
from datetime import datetime

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["houses"])
log = logging.getLogger(__name__)


class HouseCreate(BaseModel):
    address: str
    list_price: float | None = None
    sqft: int | None = None
    beds: float | None = None
    baths: float | None = None
    listing_url: str | None = None
    scheduled_at: datetime | None = None


class HouseOut(BaseModel):
    id: str
    tour_id: str
    address: str
    list_price: float | None
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
    audio_url: str | None
    video_url: str | None
    synthesis_md: str | None


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
    return HouseOut(**res.data[0])


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
    return [HouseOut(**h) for h in res.data or []]


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
    return [HouseOut(**h) for h in res.data]


@router.get("/houses/{house_id}", response_model=HouseOut)
def get_house(house_id: str, user: AuthUser = Depends(current_user)) -> HouseOut:
    return HouseOut(**get_house_for_user(house_id, user.id))


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
