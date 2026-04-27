"""Backend dispatch for the measured floor plan Modal worker.

POST /houses/{id}/measure-floorplan
    Set status=pending, spawn Modal job, return immediately. The Modal
    function calls the worker `reconstruct_floor_plan` deployed in app
    `homeanalyzer-floorplan`. When it finishes, a separate background
    task here polls the result and writes it to the houses row.

GET /houses/{id}/measured-floorplan-status
    Returns the current status + any partial result (mostly for clients
    that aren't getting Realtime updates).
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

import sentry_sdk

from app.config import settings
from app.db.supabase import supabase
from app.deps import AuthUser, current_user
from app.routes.houses import HouseOut, _to_house_out, get_house_for_user

router = APIRouter(tags=["measured-floorplan"])
log = logging.getLogger(__name__)

MODAL_APP_NAME = "homeanalyzer-floorplan"
MODAL_FUNCTION_NAME = "reconstruct_floor_plan"


def _modal_function():
    """Lazy import + lookup so the backend doesn't pay the modal SDK import
    cost on every request, and so it doesn't crash at startup if modal isn't
    installed in the environment."""
    if not settings.modal_token_id or not settings.modal_token_secret:
        raise RuntimeError(
            "MODAL_TOKEN_ID / MODAL_TOKEN_SECRET not configured in env"
        )
    os.environ.setdefault("MODAL_TOKEN_ID", settings.modal_token_id)
    os.environ.setdefault("MODAL_TOKEN_SECRET", settings.modal_token_secret)

    import modal

    return modal.Function.from_name(MODAL_APP_NAME, MODAL_FUNCTION_NAME)


@router.post("/houses/{house_id}/measure-floorplan", response_model=HouseOut)
def start_measure_floorplan(
    house_id: str,
    background: BackgroundTasks,
    user: AuthUser = Depends(current_user),
) -> HouseOut:
    """Kick off a measured floor-plan reconstruction job on Modal."""
    if not settings.enable_measured_floorplan:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Measured floor plan is disabled (ENABLE_MEASURED_FLOORPLAN=false)",
        )

    house = get_house_for_user(house_id, user.id)
    if not house.get("video_url"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No video archived for this house yet. Run a tour first.",
        )

    sb = supabase()
    sb.table("houses").update(
        {
            "measured_floor_plan_status": "pending",
            "measured_floor_plan_error": None,
            "measured_floor_plan_started_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", house_id).execute()

    background.add_task(
        _run_modal_job,
        house_id=house_id,
        video_storage_path=house["video_url"],
        schematic=house.get("floor_plan_json"),
    )

    fresh = (
        sb.table("houses").select("*").eq("id", house_id).limit(1).execute()
    )
    return _to_house_out(fresh.data[0])


def _run_modal_job(
    house_id: str, video_storage_path: str, schematic: dict | None
) -> None:
    """Background task: blocking-call the Modal function, write result back."""
    log.info("measured floorplan job start house=%s", house_id)
    sb = supabase()

    try:
        fn = _modal_function()
    except Exception as e:
        log.exception("modal function lookup failed for %s", house_id)
        sentry_sdk.capture_exception(e)
        sb.table("houses").update(
            {
                "measured_floor_plan_status": "failed",
                "measured_floor_plan_error": f"Modal not configured: {e}",
            }
        ).eq("id", house_id).execute()
        return

    try:
        # Modal's Function.remote() blocks until the worker returns. Since
        # we're already in a FastAPI BackgroundTask, blocking here is fine —
        # the HTTP request has already returned to the client.
        result = fn.remote(
            house_id=house_id,
            video_storage_path=video_storage_path,
            schematic=schematic,
        )
    except Exception as e:
        log.exception("modal job crashed for %s", house_id)
        sentry_sdk.capture_exception(e)
        sb.table("houses").update(
            {
                "measured_floor_plan_status": "failed",
                "measured_floor_plan_error": str(e)[:500],
            }
        ).eq("id", house_id).execute()
        return

    log.info(
        "measured floorplan job done house=%s rooms=%d confidence=%s",
        house_id,
        len(result.get("rooms", [])),
        result.get("confidence"),
    )
    sb.table("houses").update(
        {
            "measured_floor_plan_status": "ready",
            "measured_floor_plan_json": result,
            "measured_floor_plan_error": None,
        }
    ).eq("id", house_id).execute()


class MeasuredStatusOut(BaseModel):
    status: str | None
    started_at: datetime | None
    error: str | None
    plan: dict | None


@router.get(
    "/houses/{house_id}/measured-floorplan-status",
    response_model=MeasuredStatusOut,
)
def measured_status(
    house_id: str, user: AuthUser = Depends(current_user)
) -> MeasuredStatusOut:
    house = get_house_for_user(house_id, user.id)
    return MeasuredStatusOut(
        status=house.get("measured_floor_plan_status"),
        started_at=house.get("measured_floor_plan_started_at"),
        error=house.get("measured_floor_plan_error"),
        plan=house.get("measured_floor_plan_json"),
    )
