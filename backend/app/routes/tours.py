import logging
import secrets
from datetime import datetime, timezone

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


class TourSummary(BaseModel):
    id: str
    owner_user_id: str
    name: str
    location: str | None
    zoom_pmr_url: str | None
    status: str
    created_at: datetime
    house_count: int
    completed_count: int
    in_progress_count: int
    avg_score: float | None
    last_activity_at: datetime | None


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


class QuickTourRequest(BaseModel):
    address: str
    list_price: float | None = None
    price_kind: str | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: float | None = None


class QuickTourResponse(BaseModel):
    tour_id: str
    house_id: str
    tour_was_created: bool


@router.post("/quick", response_model=QuickTourResponse)
def quick_tour(
    payload: QuickTourRequest, user: AuthUser = Depends(current_user)
) -> QuickTourResponse:
    """Spontaneous tour: address-only flow. Reuses the user's most recent
    tour if it was created within the last 7 days, else mints a fresh tour
    named "Tour {YYYY-MM-DD}". Adds a house under it. Returns the new
    house_id so the client can navigate straight to it."""
    from datetime import timedelta

    address = payload.address.strip()
    if len(address) < 4:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Address required (min 4 chars)"
        )

    sb = supabase()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).isoformat()

    recent = (
        sb.table("tours")
        .select("*")
        .eq("owner_user_id", user.id)
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if recent.data:
        tour = recent.data[0]
        tour_was_created = False
    else:
        u = (
            sb.table("users")
            .select("default_zoom_url")
            .eq("id", user.id)
            .limit(1)
            .execute()
        )
        zoom = (u.data[0] if u.data else {}).get("default_zoom_url")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tour_res = (
            sb.table("tours")
            .insert(
                {
                    "owner_user_id": user.id,
                    "name": f"Tour {today}",
                    "location": None,
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
        tour_was_created = True

    house_payload = {
        "tour_id": tour["id"],
        "address": address,
        "status": "upcoming",
    }
    if payload.list_price is not None:
        house_payload["list_price"] = payload.list_price
    if payload.price_kind:
        house_payload["price_kind"] = payload.price_kind
    if payload.beds is not None:
        house_payload["beds"] = payload.beds
    if payload.baths is not None:
        house_payload["baths"] = payload.baths
    if payload.sqft is not None:
        house_payload["sqft"] = payload.sqft

    house_res = sb.table("houses").insert(house_payload).execute()
    house = house_res.data[0]

    return QuickTourResponse(
        tour_id=tour["id"],
        house_id=house["id"],
        tour_was_created=tour_was_created,
    )


@router.get("", response_model=list[TourSummary])
def list_tours(user: AuthUser = Depends(current_user)) -> list[TourSummary]:
    sb = supabase()
    res = (
        sb.table("tour_participants")
        .select("tours(*)")
        .eq("user_id", user.id)
        .execute()
    )
    tours = [row["tours"] for row in res.data if row.get("tours")]
    tours.sort(key=lambda t: t["created_at"], reverse=True)
    if not tours:
        return []

    tour_ids = [t["id"] for t in tours]
    houses_res = (
        sb.table("houses")
        .select("tour_id, status, overall_score, tour_started_at")
        .in_("tour_id", tour_ids)
        .execute()
    )
    by_tour: dict[str, list[dict]] = {tid: [] for tid in tour_ids}
    for h in houses_res.data or []:
        by_tour.setdefault(h["tour_id"], []).append(h)

    out: list[TourSummary] = []
    for t in tours:
        hs = by_tour.get(t["id"], [])
        scores = [h["overall_score"] for h in hs if h.get("overall_score") is not None]
        in_progress = sum(
            1 for h in hs if h.get("status") in ("touring", "synthesizing")
        )
        completed = sum(1 for h in hs if h.get("status") == "completed")
        last_activity = None
        for h in hs:
            ts = h.get("tour_started_at")
            if ts and (last_activity is None or ts > last_activity):
                last_activity = ts
        out.append(
            TourSummary(
                **t,
                house_count=len(hs),
                completed_count=completed,
                in_progress_count=in_progress,
                avg_score=(sum(scores) / len(scores)) if scores else None,
                last_activity_at=last_activity,
            )
        )
    return out


@router.get("/{tour_id}", response_model=TourOut)
def get_tour(tour_id: str, user: AuthUser = Depends(current_user)) -> TourOut:
    return TourOut(**_get_tour_for_user(tour_id, user.id))


class ShareOut(BaseModel):
    share_token: str | None
    shared_at: datetime | None


@router.post("/{tour_id}/share", response_model=ShareOut)
def create_share_link(
    tour_id: str, user: AuthUser = Depends(current_user)
) -> ShareOut:
    """Mint (or rotate) a share token for the tour. Owner only."""
    tour = _get_tour_for_user(tour_id, user.id)
    if tour["owner_user_id"] != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the tour owner can share"
        )
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat()
    sb = supabase()
    sb.table("tours").update(
        {"share_token": token, "shared_at": now}
    ).eq("id", tour_id).execute()
    return ShareOut(share_token=token, shared_at=datetime.fromisoformat(now))


@router.delete("/{tour_id}/share", response_model=ShareOut)
def revoke_share_link(
    tour_id: str, user: AuthUser = Depends(current_user)
) -> ShareOut:
    tour = _get_tour_for_user(tour_id, user.id)
    if tour["owner_user_id"] != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the tour owner can revoke"
        )
    sb = supabase()
    sb.table("tours").update(
        {"share_token": None, "shared_at": None}
    ).eq("id", tour_id).execute()
    return ShareOut(share_token=None, shared_at=None)


@router.get("/{tour_id}/share", response_model=ShareOut)
def get_share_link(
    tour_id: str, user: AuthUser = Depends(current_user)
) -> ShareOut:
    tour = _get_tour_for_user(tour_id, user.id)
    if tour["owner_user_id"] != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the tour owner can view shares"
        )
    sb = supabase()
    res = (
        sb.table("tours")
        .select("share_token, shared_at")
        .eq("id", tour_id)
        .single()
        .execute()
    )
    row = res.data or {}
    return ShareOut(
        share_token=row.get("share_token"),
        shared_at=row.get("shared_at"),
    )


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
