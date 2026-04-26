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

    # Try several auth variants against several endpoints. Print all results so
    # we can disambiguate "wrong header name", "wrong endpoint", "bad key".
    variants = [
        {
            "name": "v1 GET meeting_data, x-meeting-baas-api-key",
            "method": "GET",
            "url": "https://api.meetingbaas.com/bots/meeting_data",
            "params": {"bot_id": "00000000-0000-0000-0000-000000000000"},
            "headers": {"x-meeting-baas-api-key": key},
        },
        {
            "name": "v1 GET meeting_data, Authorization Bearer",
            "method": "GET",
            "url": "https://api.meetingbaas.com/bots/meeting_data",
            "params": {"bot_id": "00000000-0000-0000-0000-000000000000"},
            "headers": {"Authorization": f"Bearer {key}"},
        },
        {
            "name": "v1 LIST bots, x-meeting-baas-api-key",
            "method": "GET",
            "url": "https://api.meetingbaas.com/bots",
            "headers": {"x-meeting-baas-api-key": key},
        },
        {
            "name": "v1 POST bots minimal, x-meeting-baas-api-key",
            "method": "POST",
            "url": "https://api.meetingbaas.com/bots/",
            "headers": {"x-meeting-baas-api-key": key},
            "json": {
                "meeting_url": "https://zoom.us/j/0",
                "bot_name": "Debug Probe",
                "reserved": False,
            },
        },
    ]

    results = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for v in variants:
            try:
                r = await client.request(
                    v["method"],
                    v["url"],
                    headers=v.get("headers"),
                    params=v.get("params"),
                    json=v.get("json"),
                )
                results.append(
                    {
                        "variant": v["name"],
                        "status": r.status_code,
                        "body": r.text[:300],
                    }
                )
            except Exception as e:
                results.append({"variant": v["name"], "error": repr(e)})

    return {"masked": masked, "results": results}
