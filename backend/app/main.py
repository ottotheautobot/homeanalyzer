import logging

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

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
    measured_floorplan,
    me,
    realtime,
    streams,
    tours,
    webhooks,
)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
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
app.include_router(realtime.router)
app.include_router(webhooks.router)
app.include_router(streams.router)
app.include_router(compare.router)
app.include_router(measured_floorplan.router)
app.include_router(debug.router)


@app.get("/health")
def health():
    return {"status": "ok"}
