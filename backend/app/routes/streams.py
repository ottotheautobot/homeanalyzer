"""WebSocket endpoint Meeting BaaS dials with raw PCM16LE @ 16kHz mono.

Bridges that stream into Deepgram's streaming STT, writes finals to the
transcripts table, and nudges the realtime extractor.

Failure mode: if Deepgram drops mid-tour, live observations stop until the
user reconnects (rare). Post-meeting `bot.completed` still gives us the full
transcript file via the same extraction path in webhooks.py as a backstop.
"""

import asyncio
import logging

import sentry_sdk
from deepgram import AsyncDeepgramClient
from deepgram.listen.v1 import ListenV1Results
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.db.supabase import supabase
from app.realtime import state, tokens
from app.realtime.extractor import maybe_extract

log = logging.getLogger(__name__)

router = APIRouter(tags=["streams"])


def _deepgram() -> AsyncDeepgramClient:
    return AsyncDeepgramClient(api_key=settings.deepgram_api_key)


def _extract_speaker(result: ListenV1Results) -> str | None:
    if not result.channel.alternatives:
        return None
    words = result.channel.alternatives[0].words or []
    if not words:
        return None
    spk = words[0].speaker
    return f"Speaker {int(spk)}" if spk is not None else None


@router.websocket("/streams/audio/{house_id}")
async def stream_audio(
    websocket: WebSocket, house_id: str, token: str
) -> None:
    log.info(
        "stream dial received house=%s client=%s headers=%s",
        house_id,
        websocket.client,
        {k.lower(): v for k, v in websocket.headers.items() if k.lower() not in ("authorization", "cookie")},
    )

    if not tokens.verify(house_id, token):
        log.warning("stream dial rejected: bad token house=%s", house_id)
        await websocket.close(code=1008, reason="bad token")
        return

    sb = supabase()
    house = (
        sb.table("houses")
        .select("bot_id")
        .eq("id", house_id)
        .limit(1)
        .execute()
    )
    bot_id = (house.data[0] if house.data else {}).get("bot_id")
    if not bot_id:
        log.warning("stream dial rejected: no bot_id on house %s", house_id)
        await websocket.close(code=1011, reason="house has no active bot")
        return

    await websocket.accept()
    log.info("stream accepted bot=%s house=%s", bot_id, house_id)

    state.get_or_create(bot_id, house_id)
    inserted_keys: set[float] = set()

    async def handle_final(result: ListenV1Results) -> None:
        if not result.channel.alternatives:
            return
        text = (result.channel.alternatives[0].transcript or "").strip()
        if not text:
            return
        start = float(result.start)
        end = start + float(result.duration)
        key = round(start, 3)
        if key in inserted_keys:
            return
        inserted_keys.add(key)

        sb = supabase()
        try:
            sb.table("transcripts").insert(
                {
                    "house_id": house_id,
                    "bot_id": bot_id,
                    "speaker": _extract_speaker(result),
                    "text": text,
                    "start_seconds": start,
                    "end_seconds": end,
                    "processed": False,
                }
            ).execute()
        except Exception as e:
            # Most likely UNIQUE(bot_id, start_seconds) on a duplicate emit.
            log.debug("transcript insert skipped: %s", e)
            return

        asyncio.create_task(maybe_extract(bot_id))

    try:
        async with _deepgram().listen.v1.connect(
            model="nova-3",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            smart_format=True,
            punctuate=True,
            diarize=True,
            interim_results=False,
            endpointing=300,
        ) as dg_ws:

            async def recv_loop() -> None:
                try:
                    async for msg in dg_ws:
                        if isinstance(msg, ListenV1Results) and msg.is_final:
                            await handle_final(msg)
                except Exception as e:
                    log.exception("deepgram recv loop crashed")
                    sentry_sdk.capture_exception(e)

            recv_task = asyncio.create_task(recv_loop())

            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    data = msg.get("bytes")
                    if data:
                        await dg_ws.send_media(data)
            except WebSocketDisconnect:
                pass
            finally:
                try:
                    await dg_ws.send_close_stream()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(recv_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    recv_task.cancel()
    except Exception as e:
        log.exception("stream handler crashed")
        sentry_sdk.capture_exception(e)
    finally:
        try:
            await maybe_extract(bot_id, force=True)
        except Exception as e:
            sentry_sdk.capture_exception(e)
        log.info("stream close bot=%s", bot_id)
