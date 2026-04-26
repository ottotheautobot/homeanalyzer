from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(prefix="/tours", tags=["tours"])


class TourCreate(BaseModel):
    name: str
    location: str | None = None
    zoom_pmr_url: str | None = None


class TourOut(BaseModel):
    id: str
    owner_user_id: str
    name: str
    location: str | None
    zoom_pmr_url: str | None
    status: str
    created_at: datetime


def _get_tour_for_user(tour_id: str, user_id: str) -> dict:
    sb = supabase()
    res = (
        sb.table("tour_participants")
        .select("tour_id, tours(*)")
        .eq("tour_id", tour_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour not found")
    return res.data[0]["tours"]


@router.post("", response_model=TourOut, status_code=status.HTTP_201_CREATED)
def create_tour(payload: TourCreate, user: AuthUser = Depends(current_user)) -> TourOut:
    sb = supabase()
    zoom = payload.zoom_pmr_url
    if not zoom:
        u = (
            sb.table("users")
            .select("default_zoom_url")
            .eq("id", user.id)
            .limit(1)
            .execute()
        )
        zoom = (u.data[0] if u.data else {}).get("default_zoom_url")
    tour_res = (
        sb.table("tours")
        .insert(
            {
                "owner_user_id": user.id,
                "name": payload.name,
                "location": payload.location,
                "zoom_pmr_url": zoom,
            }
        )
        .execute()
    )
    tour = tour_res.data[0]

    sb.table("tour_participants").upsert(
        {"tour_id": tour["id"], "user_id": user.id, "role": "buyer"},
        on_conflict="tour_id,user_id",
    ).execute()

    return TourOut(**tour)


@router.get("", response_model=list[TourOut])
def list_tours(user: AuthUser = Depends(current_user)) -> list[TourOut]:
    sb = supabase()
    res = (
        sb.table("tour_participants")
        .select("tours(*)")
        .eq("user_id", user.id)
        .execute()
    )
    tours = [row["tours"] for row in res.data if row.get("tours")]
    tours.sort(key=lambda t: t["created_at"], reverse=True)
    return [TourOut(**t) for t in tours]


@router.get("/{tour_id}", response_model=TourOut)
def get_tour(tour_id: str, user: AuthUser = Depends(current_user)) -> TourOut:
    return TourOut(**_get_tour_for_user(tour_id, user.id))
