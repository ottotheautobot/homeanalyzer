"""Backend dispatch for the measured floor plan Modal worker.

Architecture: spawn-and-poll.

  POST /houses/{id}/measure-floorplan
    Sets status=pending, calls modal.spawn() to fire-and-forget the job,
    persists the FunctionCall id on the row, returns immediately.

  POST /houses/{id}/measure-floorplan-poll
    Looks up the FunctionCall by id, does a non-blocking get(timeout=0).
    On result -> writes ready+json. On TimeoutError -> stays pending.
    On other errors -> writes failed. Frontend polls this every ~30s
    while pending so the result lands even if Railway restarted between
    spawn and completion.

  DELETE /houses/{id}/measure-floorplan
    Cancels the in-flight Modal call (if any) and clears local status.
    Saves ~5 min of GPU time per cancel.

  GET /houses/{id}/measured-floorplan-status
    Snapshot read, mostly for clients without Realtime.

Old behavior (synchronous remote() in a daemon thread) lost results when
the Railway worker restarted mid-job. spawn() decouples job lifetime from
worker lifetime.
"""

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
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


def spawn_modal_job(
    house_id: str, video_storage_path: str, schematic: dict | None
) -> str | None:
    """Fire the Modal function asynchronously, return its FunctionCall id.

    Returns None on configuration/spawn failure (caller marks failed)."""
    try:
        fn = _modal_function()
    except Exception as e:
        log.exception("modal function lookup failed for %s", house_id)
        sentry_sdk.capture_exception(e)
        supabase().table("houses").update(
            {
                "measured_floor_plan_status": "failed",
                "measured_floor_plan_error": f"Modal not configured: {e}",
                "measured_floor_plan_modal_call_id": None,
            }
        ).eq("id", house_id).execute()
        return None

    try:
        call = fn.spawn(
            house_id=house_id,
            video_storage_path=video_storage_path,
            schematic=schematic,
        )
    except Exception as e:
        log.exception("modal spawn failed for %s", house_id)
        sentry_sdk.capture_exception(e)
        supabase().table("houses").update(
            {
                "measured_floor_plan_status": "failed",
                "measured_floor_plan_error": str(e)[:500],
                "measured_floor_plan_modal_call_id": None,
            }
        ).eq("id", house_id).execute()
        return None

    log.info(
        "measured floorplan spawned house=%s call_id=%s",
        house_id,
        call.object_id,
    )
    return call.object_id


@router.post("/houses/{house_id}/measure-floorplan", response_model=HouseOut)
def start_measure_floorplan(
    house_id: str, user: AuthUser = Depends(current_user)
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
    # Set pending up-front so the UI flips immediately; spawn fills in the
    # call_id (or rolls back to failed inside spawn_modal_job).
    sb.table("houses").update(
        {
            "measured_floor_plan_status": "pending",
            "measured_floor_plan_error": None,
            "measured_floor_plan_started_at": datetime.now(timezone.utc).isoformat(),
            "measured_floor_plan_modal_call_id": None,
        }
    ).eq("id", house_id).execute()

    call_id = spawn_modal_job(
        house_id=house_id,
        video_storage_path=house["video_url"],
        schematic=house.get("floor_plan_json"),
    )
    if call_id:
        sb.table("houses").update(
            {"measured_floor_plan_modal_call_id": call_id}
        ).eq("id", house_id).execute()

    fresh = (
        sb.table("houses").select("*").eq("id", house_id).limit(1).execute()
    )
    return _to_house_out(fresh.data[0])


@router.post(
    "/houses/{house_id}/measure-floorplan-poll", response_model=HouseOut
)
def poll_measure_floorplan(
    house_id: str, user: AuthUser = Depends(current_user)
) -> HouseOut:
    """Non-blocking check on the in-flight Modal call. Frontend hits this
    every ~30s while status is pending so the result lands without depending
    on the original worker process surviving."""
    house = get_house_for_user(house_id, user.id)
    sb = supabase()

    status_now = house.get("measured_floor_plan_status")
    call_id = house.get("measured_floor_plan_modal_call_id")
    if status_now != "pending":
        return _to_house_out(house)
    if not call_id:
        # Pending but no call_id — pre-spawn-architecture row, can't be
        # reconciled. Tell the user to retry.
        sb.table("houses").update(
            {
                "measured_floor_plan_status": "failed",
                "measured_floor_plan_error": (
                    "Lost track of the Modal job (likely a worker restart "
                    "before persistence). Click Retry to start fresh."
                ),
            }
        ).eq("id", house_id).execute()
        return _to_house_out(get_house_for_user(house_id, user.id))

    # Real poll path.
    try:
        os.environ.setdefault("MODAL_TOKEN_ID", settings.modal_token_id)
        os.environ.setdefault("MODAL_TOKEN_SECRET", settings.modal_token_secret)
        import modal
        from modal.exception import OutputExpiredError

        fc = modal.FunctionCall.from_id(call_id)
        try:
            result = fc.get(timeout=0)
        except TimeoutError:
            return _to_house_out(house)
        except OutputExpiredError:
            sb.table("houses").update(
                {
                    "measured_floor_plan_status": "failed",
                    "measured_floor_plan_error": (
                        "Modal output expired before we polled it. Retry."
                    ),
                }
            ).eq("id", house_id).execute()
            return _to_house_out(get_house_for_user(house_id, user.id))

        # Got a result — write it.
        log.info(
            "poll completed house=%s rooms=%d confidence=%s",
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
        return _to_house_out(get_house_for_user(house_id, user.id))
    except Exception as e:
        log.exception("modal poll crashed for %s", house_id)
        sentry_sdk.capture_exception(e)
        sb.table("houses").update(
            {
                "measured_floor_plan_status": "failed",
                "measured_floor_plan_error": str(e)[:500],
            }
        ).eq("id", house_id).execute()
        return _to_house_out(get_house_for_user(house_id, user.id))


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


@router.delete(
    "/houses/{house_id}/measure-floorplan", response_model=HouseOut
)
def cancel_measure_floorplan(
    house_id: str, user: AuthUser = Depends(current_user)
) -> HouseOut:
    """Clear the pending/failed status. If we have a Modal FunctionCall id,
    cancel the in-flight job too — saves ~5 min of GPU time per cancel."""
    house = get_house_for_user(house_id, user.id)
    call_id = house.get("measured_floor_plan_modal_call_id")
    if call_id:
        try:
            os.environ.setdefault("MODAL_TOKEN_ID", settings.modal_token_id)
            os.environ.setdefault(
                "MODAL_TOKEN_SECRET", settings.modal_token_secret
            )
            import modal

            modal.FunctionCall.from_id(call_id).cancel()
            log.info("cancelled modal call %s for house %s", call_id, house_id)
        except Exception:
            log.exception("modal cancel failed for %s; clearing locally", call_id)

    sb = supabase()
    sb.table("houses").update(
        {
            "measured_floor_plan_status": None,
            "measured_floor_plan_error": None,
            "measured_floor_plan_started_at": None,
            "measured_floor_plan_modal_call_id": None,
        }
    ).eq("id", house_id).execute()
    return _to_house_out(get_house_for_user(house_id, user.id))
