from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["houses"])


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
