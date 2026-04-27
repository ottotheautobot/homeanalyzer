"""Public read-only routes for shared tours.

The owner mints a token via POST /tours/{id}/share. Anyone with the token
URL can call GET /share/{token} to read the tour + its houses (briefs +
floor plans + observations) without auth. Service-role lookup bypasses RLS;
we only return rows whose share_token matches.

Sensitive data (raw transcripts, audio/video URLs, observations sourced as
private notes) is filtered out — this is meant for sharing the *brief*,
not the recording.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.db.supabase import supabase

router = APIRouter(prefix="/share", tags=["share"])


class SharedHouse(BaseModel):
    id: str
    address: str
    list_price: float | None
    price_kind: str | None
    beds: float | None
    baths: float | None
    sqft: float | None
    photo_signed_url: str | None
    status: str
    overall_score: float | None
    synthesis_md: str | None
    floor_plan_json: dict[str, Any] | None
    measured_floor_plan_json: dict[str, Any] | None
    measured_floor_plan_status: str | None


class SharedObservation(BaseModel):
    id: str
    room: str | None
    category: str
    content: str
    severity: str | None


class SharedTour(BaseModel):
    tour_id: str
    name: str
    location: str | None
    status: str
    shared_at: datetime
    houses: list[SharedHouse]
    observations_by_house: dict[str, list[SharedObservation]]


@router.get("/{token}", response_model=SharedTour)
def get_shared_tour(token: str) -> SharedTour:
    if len(token) < 16:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    sb = supabase()
    tres = (
        sb.table("tours")
        .select(
            "id, name, location, status, shared_at, share_token"
        )
        .eq("share_token", token)
        .limit(1)
        .execute()
    )
    if not tres.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    tour = tres.data[0]

    hres = (
        sb.table("houses")
        .select(
            "id, address, list_price, price_kind, beds, baths, sqft, "
            "photo_signed_url, status, overall_score, synthesis_md, "
            "floor_plan_json, measured_floor_plan_json, "
            "measured_floor_plan_status"
        )
        .eq("tour_id", tour["id"])
        .order("created_at")
        .execute()
    )
    houses_rows = hres.data or []
    house_ids = [h["id"] for h in houses_rows]

    obs_by_house: dict[str, list[SharedObservation]] = {hid: [] for hid in house_ids}
    if house_ids:
        ores = (
            sb.table("observations")
            .select("id, house_id, room, category, content, severity, source")
            .in_("house_id", house_ids)
            .order("created_at")
            .execute()
        )
        for o in ores.data or []:
            # Hide private notes — only share what came from audio/photo analysis.
            if o.get("source") == "private_note":
                continue
            obs_by_house.setdefault(o["house_id"], []).append(
                SharedObservation(
                    id=o["id"],
                    room=o.get("room"),
                    category=o["category"],
                    content=o["content"],
                    severity=o.get("severity"),
                )
            )

    return SharedTour(
        tour_id=tour["id"],
        name=tour["name"],
        location=tour.get("location"),
        status=tour["status"],
        shared_at=tour["shared_at"],
        houses=[SharedHouse(**h) for h in houses_rows],
        observations_by_house=obs_by_house,
    )
