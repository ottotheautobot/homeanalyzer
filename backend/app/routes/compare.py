"""Cross-house comparison endpoint.

Brief locks "stuff all house briefs into Sonnet 4.6 context, no RAG, no
vector DB." We honor that — the entire selection of houses goes into one
prompt with the user's question.

Multi-tour selection is supported (per user's clarification): houses can
be from any tour the user is a participant of.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.supabase import supabase
from app.deps import AuthUser, current_user
from app.llm.compare import compare_houses

router = APIRouter(tags=["compare"])
log = logging.getLogger(__name__)


class CompareRequest(BaseModel):
    house_ids: list[str] = Field(min_length=1, max_length=20)
    query: str = Field(min_length=1, max_length=2000)


class CompareResponse(BaseModel):
    answer: str
    used_house_ids: list[str]


@router.post("/compare", response_model=CompareResponse)
def compare(
    body: CompareRequest, user: AuthUser = Depends(current_user)
) -> CompareResponse:
    sb = supabase()

    houses_res = (
        sb.table("houses")
        .select("*")
        .in_("id", body.house_ids)
        .execute()
    )
    houses = houses_res.data or []
    if not houses:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No houses found")

    tour_ids = list({h["tour_id"] for h in houses})
    parts_res = (
        sb.table("tour_participants")
        .select("tour_id")
        .eq("user_id", user.id)
        .in_("tour_id", tour_ids)
        .execute()
    )
    permitted = {p["tour_id"] for p in (parts_res.data or [])}
    not_permitted = [h["address"] for h in houses if h["tour_id"] not in permitted]
    if not_permitted:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Not a participant on tour(s) for: {', '.join(not_permitted)}",
        )

    observations_by_house: dict[str, list[dict]] = {}
    for h in houses:
        obs = (
            sb.table("observations")
            .select("room, category, content, severity")
            .eq("house_id", h["id"])
            .order("created_at")
            .execute()
        )
        observations_by_house[h["id"]] = obs.data or []

    try:
        answer = compare_houses(houses, observations_by_house, body.query)
    except Exception as e:
        log.exception("compare LLM call failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"LLM comparison failed: {e}"
        ) from e

    return CompareResponse(answer=answer, used_house_ids=[h["id"] for h in houses])
