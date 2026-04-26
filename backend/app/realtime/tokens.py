"""HMAC-signed tokens for per-house WebSocket URLs.

Meeting BaaS dials our WS URL as a client and does not forward auth headers,
so we embed a token in the URL itself. The token binds the URL to a specific
house_id (we don't know bot_id at URL-generation time — Meeting BaaS returns
that after we ask it to start). The WS handler reads the real bot_id from
the houses row at connection time.
"""

import hmac
import hashlib

from app.config import settings


def sign(house_id: str) -> str:
    msg = f"ws:{house_id}".encode()
    key = settings.streaming_url_secret.encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify(house_id: str, token: str) -> bool:
    return hmac.compare_digest(sign(house_id), token)
