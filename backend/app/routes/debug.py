"""Debug-only endpoints. Auth-required so they're not internet-public."""

import httpx
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import AuthUser, current_user

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/meetingbaas")
async def debug_meetingbaas(_: AuthUser = Depends(current_user)) -> dict:
    key = settings.meetingbaas_api_key or ""
    masked = {
        "key_loaded": bool(key),
        "key_length": len(key),
        "key_prefix": key[:4] if key else "",
        "key_suffix": key[-4:] if len(key) > 8 else "",
    }
    if not key:
        return {"masked": masked, "ping": "skipped"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.meetingbaas.com/bots/meeting_data",
                headers={"x-meeting-baas-api-key": key},
                params={"bot_id": "00000000-0000-0000-0000-000000000000"},
            )
        body = r.text[:400]
    except Exception as e:
        return {"masked": masked, "ping_error": repr(e)}

    return {
        "masked": masked,
        "ping_status": r.status_code,
        "ping_body": body,
    }
