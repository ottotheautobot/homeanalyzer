"""Debug-only endpoints. Auth-required so they're not internet-public."""

import httpx
from fastapi import APIRouter, Depends

from app.config import settings
from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/finalize/{bot_id}")
async def debug_finalize(
    bot_id: str, _: AuthUser = Depends(current_user)
) -> dict:
    """Manually run the post-meeting pipeline for a bot, bypassing the
    webhook. Downloads the audio from MB's S3 (4h TTL) and runs it through
    our Whisper -> Haiku -> Sonnet pipeline. Use when MB's webhook isn't
    reaching us / signature verify is misconfigured.
    """
    import time
    from uuid import uuid4

    from app.routes.audio import _process_audio_upload

    sb = supabase()
    h = (
        sb.table("houses")
        .select("id, address, bot_id, status")
        .eq("bot_id", bot_id)
        .limit(1)
        .execute()
    )
    if not h.data:
        return {"error": f"no house has bot_id={bot_id}"}
    house_id = h.data[0]["id"]

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://api.meetingbaas.com/bots/meeting_data",
            headers={"x-meeting-baas-api-key": settings.meetingbaas_api_key},
            params={"bot_id": bot_id},
        )
    r.raise_for_status()
    data = r.json()["bot_data"]
    audio_url = data.get("audio")
    if not audio_url:
        return {"error": "no audio URL in MB bot data"}

    async with httpx.AsyncClient(timeout=300.0) as client:
        ar = await client.get(audio_url, follow_redirects=True)
        ar.raise_for_status()
        audio_bytes = ar.content

    storage_path = f"{house_id}/{int(time.time())}-{uuid4().hex[:8]}.wav"
    sb.storage.from_("tour-audio").upload(
        path=storage_path,
        file=audio_bytes,
        file_options={"content-type": "audio/wav", "upsert": "true"},
    )
    sb.table("houses").update(
        {"audio_url": storage_path, "status": "touring"}
    ).eq("id", house_id).execute()

    _process_audio_upload(house_id, audio_bytes, "audio/wav", "wav")

    return {
        "ok": True,
        "house": house_id,
        "bot_id": bot_id,
        "audio_bytes": len(audio_bytes),
        "storage_path": storage_path,
    }


@router.get("/streaming-url")
async def debug_streaming_url(_: AuthUser = Depends(current_user)) -> dict:
    """Show the streaming URL we'd build for the latest house (without secrets).

    Helps verify BACKEND_URL is what we think and that the wss:// rewrite
    is correct.
    """
    from app.realtime import tokens

    sb = supabase()
    h = (
        sb.table("houses")
        .select("id, address")
        .order("tour_started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not h.data:
        return {"error": "no houses"}
    house_id = h.data[0]["id"]
    token = tokens.sign(house_id)

    base = settings.backend_url.rstrip("/")
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://"):]
    else:
        ws_base = base
    return {
        "backend_url": base,
        "ws_base": ws_base,
        "example_streaming_url": f"{ws_base}/streams/audio/{house_id}?token={token[:8]}...",
    }


@router.get("/bot")
async def debug_bot(_: AuthUser = Depends(current_user)) -> dict:
    """Look up the latest bot we created and ask MB for its current state."""
    sb = supabase()
    h = (
        sb.table("houses")
        .select("id, address, status, bot_id, tour_started_at")
        .not_.is_("bot_id", "null")
        .order("tour_started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not h.data:
        return {"error": "no house with a bot_id found"}
    house = h.data[0]
    bot_id = house["bot_id"]

    headers = {"x-meeting-baas-api-key": settings.meetingbaas_api_key}
    out: dict = {"house": house, "probes": []}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for path in (
            f"/bots/{bot_id}",
            f"/bots/meeting_data?bot_id={bot_id}",
        ):
            try:
                r = await client.get(
                    f"https://api.meetingbaas.com{path}", headers=headers
                )
                out["probes"].append(
                    {"path": path, "status": r.status_code, "body": r.text[:4000]}
                )
            except Exception as e:
                out["probes"].append({"path": path, "error": repr(e)})

    return out


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
