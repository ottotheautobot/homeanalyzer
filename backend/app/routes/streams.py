"""WebSocket endpoint Meeting BaaS dials with raw PCM16LE @ 16kHz mono.

Bridges that stream into Deepgram's streaming STT (raw `websockets`,
not the SDK — the SDK was returning generic 400s with no actionable
error body). Writes finals to the transcripts table and nudges the
realtime extractor.

Failure mode: if Deepgram drops mid-tour, live observations stop until
the user reconnects (rare). Post-meeting `bot.completed` still gives us
the full audio file via the same Whisper path in webhooks.py as a
backstop.
"""

import asyncio
import json
import logging
import urllib.parse

import sentry_sdk
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.db.supabase import supabase
from app.realtime import state, tokens
from app.realtime.extractor import maybe_extract

log = logging.getLogger(__name__)

router = APIRouter(tags=["streams"])

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_PARAMS = {
    "model": "nova-2",
    "encoding": "linear16",
    "sample_rate": "16000",
    "channels": "1",
    "punctuate": "true",
    "diarize": "true",
    "interim_results": "false",
    "endpointing": "300",
}


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

    async def handle_final(payload: dict) -> None:
        alts = (payload.get("channel") or {}).get("alternatives") or []
        if not alts:
            return
        text = (alts[0].get("transcript") or "").strip()
        if not text:
            return
        start = float(payload.get("start", 0.0))
        duration = float(payload.get("duration", 0.0))
        end = start + duration

        speaker = None
        words = alts[0].get("words") or []
        if words and words[0].get("speaker") is not None:
            speaker = f"Speaker {int(words[0]['speaker'])}"

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
                    "speaker": speaker,
                    "text": text,
                    "start_seconds": start,
                    "end_seconds": end,
                    "processed": False,
                }
            ).execute()
        except Exception as e:
            log.debug("transcript insert skipped: %s", e)
            return

        asyncio.create_task(maybe_extract(bot_id))

    dg_url = DEEPGRAM_WS_URL + "?" + urllib.parse.urlencode(DEEPGRAM_PARAMS)
    dg_headers = {"Authorization": f"Token {settings.deepgram_api_key}"}

    try:
        async with websockets.connect(
            dg_url, additional_headers=dg_headers, max_size=2**24
        ) as dg_ws:
            log.info("deepgram WS connected for bot %s", bot_id)

            async def recv_loop() -> None:
                try:
                    async for msg in dg_ws:
                        if isinstance(msg, (bytes, bytearray)):
                            continue
                        try:
                            payload = json.loads(msg)
                        except Exception:
                            continue
                        if payload.get("type") == "Results" and payload.get("is_final"):
                            await handle_final(payload)
                except Exception as e:
                    log.exception("deepgram recv loop crashed")
                    sentry_sdk.capture_exception(e)

            async def keepalive_loop() -> None:
                """Deepgram closes the connection after ~10s without any
                audio or message. Send a KeepAlive every 5s so the bot can
                spend its first seconds joining Zoom without losing the WS."""
                try:
                    while True:
                        await asyncio.sleep(5)
                        try:
                            await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                        except Exception:
                            return
                except asyncio.CancelledError:
                    return

            recv_task = asyncio.create_task(recv_loop())
            keepalive_task = asyncio.create_task(keepalive_loop())

            try:
                frames_forwarded = 0
                text_frames = 0
                empty_frames = 0
                last_log = 0
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        log.info(
                            "MB disconnected bot=%s frames_forwarded=%d text_frames=%d empty=%d",
                            bot_id,
                            frames_forwarded,
                            text_frames,
                            empty_frames,
                        )
                        break
                    data = msg.get("bytes")
                    if data:
                        await dg_ws.send(data)
                        frames_forwarded += 1
                        if frames_forwarded == 1:
                            log.info(
                                "first audio frame forwarded bot=%s bytes=%d",
                                bot_id,
                                len(data),
                            )
                        elif frames_forwarded - last_log >= 100:
                            last_log = frames_forwarded
                            log.info(
                                "audio frames bot=%s count=%d",
                                bot_id,
                                frames_forwarded,
                            )
                    elif msg.get("text"):
                        text_frames += 1
                        if text_frames <= 3:
                            log.info(
                                "MB text frame bot=%s sample=%s",
                                bot_id,
                                msg["text"][:200],
                            )
                    else:
                        empty_frames += 1
            except WebSocketDisconnect:
                pass
            finally:
                keepalive_task.cancel()
                try:
                    await dg_ws.send(json.dumps({"type": "CloseStream"}))
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(recv_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    recv_task.cancel()
    except websockets.exceptions.InvalidStatus as e:
        log.error(
            "deepgram rejected WS upgrade: status=%s headers=%s",
            e.response.status_code,
            dict(e.response.headers),
        )
        sentry_sdk.capture_exception(e)
    except Exception as e:
        log.exception("stream handler crashed")
        sentry_sdk.capture_exception(e)
    finally:
        try:
            await maybe_extract(bot_id, force=True)
        except Exception as e:
            sentry_sdk.capture_exception(e)
        log.info("stream close bot=%s", bot_id)
