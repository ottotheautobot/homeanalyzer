import logging
import re

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


# Strip the query string from URLs that look like presigned downloads
# (Supabase Storage signed URLs, AWS S3 presigned URLs from Meeting
# BaaS). These query strings carry signing tokens / JWTs that have no
# triage value in Sentry but would expose short-lived credentials in
# event payloads. Match anything containing token= or X-Amz- — those
# cover both vendors.
_PRESIGNED_URL_RE = re.compile(
    r"(https?://[^\s?\"<>]+)\?[^\s\"<>]*(?:token=|X-Amz-)[^\s\"<>]*",
    re.IGNORECASE,
)


def _scrub(text: str) -> str:
    return _PRESIGNED_URL_RE.sub(r"\1?<scrubbed>", text)


def _scrub_event(event, _hint):
    """Sentry before_send hook — walks exception messages and
    breadcrumbs, replacing presigned-URL query strings with
    `<scrubbed>`. Mutates the event in place and returns it."""
    try:
        for exc in (event.get("exception") or {}).get("values") or []:
            if isinstance(exc.get("value"), str):
                exc["value"] = _scrub(exc["value"])
        for crumb in event.get("breadcrumbs") or {}.get("values") or []:
            if isinstance(crumb.get("message"), str):
                crumb["message"] = _scrub(crumb["message"])
        msg = event.get("message")
        if isinstance(msg, str):
            event["message"] = _scrub(msg)
        elif isinstance(msg, dict) and isinstance(msg.get("formatted"), str):
            msg["formatted"] = _scrub(msg["formatted"])
    except Exception:
        # Never let scrubbing break exception delivery.
        pass
    return event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("app").setLevel(logging.INFO)
from app.routes import (
    audio,
    compare,
    debug,
    houses,
    invites,
    me,
    realtime,
    share,
    streams,
    tours,
    video,
    webhooks,
)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
        before_send=_scrub_event,
    )

app = FastAPI(title="House Tour Notes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(tours.router)
app.include_router(houses.router)
app.include_router(invites.router)
app.include_router(audio.router)
app.include_router(video.router)
app.include_router(realtime.router)
app.include_router(webhooks.router)
app.include_router(streams.router)
app.include_router(compare.router)
app.include_router(share.router)
app.include_router(debug.router)


@app.get("/health")
def health():
    return {"status": "ok"}
