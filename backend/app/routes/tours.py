import logging
from datetime import datetime

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(prefix="/tours", tags=["tours"])
log = logging.getLogger(__name__)


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


@router.delete("/{tour_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tour(tour_id: str, user: AuthUser = Depends(current_user)) -> Response:
    """Delete a tour and ALL associated data: houses, observations, transcripts,
    participants, invites (cascaded by FK), plus the audio/video files in
    storage under each house's prefix (NOT cascaded by Postgres).
    """
    tour = _get_tour_for_user(tour_id, user.id)
    if tour["owner_user_id"] != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the tour owner can delete"
        )

    sb = supabase()
    houses = sb.table("houses").select("id").eq("tour_id", tour_id).execute()
    for h in houses.data or []:
        prefix = h["id"]
        try:
            files = sb.storage.from_("tour-audio").list(prefix) or []
            paths = [f"{prefix}/{f['name']}" for f in files if f.get("name")]
            if paths:
                sb.storage.from_("tour-audio").remove(paths)
        except Exception as e:
            log.exception("storage cleanup failed for house %s", h["id"])
            sentry_sdk.capture_exception(e)

    sb.table("tours").delete().eq("id", tour_id).execute()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
