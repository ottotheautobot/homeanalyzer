"""Live-tour control endpoints: start_tour, end_tour, next_room.

start_tour kicks the Meeting BaaS bot into a Zoom meeting and points its
audio stream at our /streams/audio WebSocket. end_tour stops the bot;
synthesis fires when the `bot.completed` webhook arrives. next_room sets
the sticky room hint and forces an immediate extraction pass.
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.db.supabase import supabase
from app.deps import AuthUser, current_user
from app.notifications import send_tour_started_email
from app.providers.meetingbaas import get_meeting_provider
from app.realtime import state, tokens
from app.realtime.extractor import maybe_extract
from app.routes.houses import get_house_for_user, HouseOut
from app.services import zoom as zoom_service

log = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


class StartTourBody(BaseModel):
    zoom_url: str | None = None


class NextRoomBody(BaseModel):
    room: str


def _backend_ws_base() -> str:
    """ws(s):// equivalent of the configured backend_url."""
    base = settings.backend_url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :]
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :]
    return base


@router.post(
    "/houses/{house_id}/start_tour",
    response_model=HouseOut,
    status_code=status.HTTP_200_OK,
)
async def start_tour(
    house_id: str,
    body: StartTourBody,
    background: BackgroundTasks,
    user: AuthUser = Depends(current_user),
) -> HouseOut:
    house = get_house_for_user(house_id, user.id)
    if house.get("bot_id"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Tour already started")

    zoom_url = body.zoom_url
    sb = supabase()
    if not zoom_url:
        tour = (
            sb.table("tours")
            .select("zoom_pmr_url")
            .eq("id", house["tour_id"])
            .limit(1)
            .execute()
        )
        zoom_url = (tour.data[0] if tour.data else {}).get("zoom_pmr_url")
    if not zoom_url:
        u = (
            sb.table("users")
            .select("default_zoom_url")
            .eq("id", user.id)
            .limit(1)
            .execute()
        )
        zoom_url = (u.data[0] if u.data else {}).get("default_zoom_url")
    if not zoom_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "We need a Zoom meeting URL to send the bot to. "
            "Either paste one here, or set a default in Settings so you don't have to enter it each time.",
        )

    provider = get_meeting_provider()
    backend = settings.backend_url.rstrip("/")
    webhook_url = f"{backend}/webhooks/meetingbaas"

    # Streaming URL is keyed on house_id (known now) + an HMAC token. The WS
    # handler reads the real bot_id from the houses row when MB connects.
    token = tokens.sign(house_id)
    qs = urlencode({"token": token})
    streaming_url = f"{_backend_ws_base()}/streams/audio/{house_id}?{qs}"

    try:
        bot_id = await provider.start_bot(
            meeting_url=zoom_url,
            bot_name="Tour Notes",
            webhook_url=webhook_url,
            streaming_input_url=streaming_url,
            extra={"house_id": house_id},
        )
    except Exception as e:
        log.exception("start_bot failed for house %s", house_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Meeting BaaS rejected start_bot: {e}"
        ) from e

    sb = supabase()
    res = (
        sb.table("houses")
        .update(
            {
                "bot_id": bot_id,
                "status": "touring",
                "tour_started_at": "now()",
            }
        )
        .eq("id", house_id)
        .execute()
    )
    state.get_or_create(bot_id, house_id)

    tour_row = (
        sb.table("tours")
        .select("name")
        .eq("id", house["tour_id"])
        .limit(1)
        .execute()
    )
    tour_name = (tour_row.data[0] if tour_row.data else {}).get("name", "")
    background.add_task(
        send_tour_started_email,
        tour_id=house["tour_id"],
        tour_name=tour_name,
        owner_user_id=user.id,
        house_id=house_id,
        house_address=house["address"],
        zoom_url=zoom_url,
    )

    return HouseOut(**res.data[0])


@router.post("/houses/{house_id}/end_tour", response_model=HouseOut)
async def end_tour(
    house_id: str, user: AuthUser = Depends(current_user)
) -> HouseOut:
    house = get_house_for_user(house_id, user.id)
    bot_id = house.get("bot_id")
    if not bot_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No active bot")

    provider = get_meeting_provider()
    try:
        await provider.stop_bot(bot_id)
    except Exception as e:
        log.exception("stop_bot failed for house %s", house_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Meeting BaaS rejected stop_bot: {e}"
        ) from e

    # Best-effort: also end the Zoom meeting itself so it closes for all
    # participants instead of staying open until the host manually leaves.
    # No-op when Zoom S2S creds aren't configured. Failure here doesn't
    # block end_tour — the bot is already stopped, which is the contract.
    sb = supabase()
    tour_row = (
        sb.table("tours")
        .select("zoom_pmr_url")
        .eq("id", house["tour_id"])
        .limit(1)
        .execute()
    )
    zoom_url = (tour_row.data[0] if tour_row.data else {}).get("zoom_pmr_url")
    if zoom_url and zoom_service.is_configured():
        try:
            await zoom_service.end_meeting(zoom_url)
        except Exception:
            log.exception("zoom end_meeting raised unexpectedly for house %s", house_id)

    res = (
        sb.table("houses")
        .update({"status": "synthesizing"})
        .eq("id", house_id)
        .execute()
    )
    return HouseOut(**res.data[0])


@router.post("/houses/{house_id}/next_room", response_model=HouseOut)
async def next_room(
    house_id: str,
    body: NextRoomBody,
    user: AuthUser = Depends(current_user),
) -> HouseOut:
    house = get_house_for_user(house_id, user.id)
    bot_id = house.get("bot_id")

    sb = supabase()
    res = (
        sb.table("houses")
        .update({"current_room": body.room})
        .eq("id", house_id)
        .execute()
    )
    if bot_id:
        state.set_room(bot_id, body.room)
        # Force an extraction now so any unprocessed lines get attributed to
        # the *previous* room, then subsequent lines pick up the new hint.
        await maybe_extract(bot_id, force=True)
    return HouseOut(**res.data[0])
