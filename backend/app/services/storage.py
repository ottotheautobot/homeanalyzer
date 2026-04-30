"""Direct Supabase Storage REST helpers — bypass storage3 for the
sign-url and signed-upload paths because storage3 holds httpx
HTTP/2 connections that drop with `Server disconnected` under load.

We've already replaced storage3 for object uploads (see webhooks.py
_put_storage_object). This module covers the sign-url paths
(`/object/sign/{bucket}/{path}` for downloads and
`/object/upload/sign/{bucket}/{path}` for upload tokens). Same
HTTP/1.1, explicit timeout, single-retry recipe."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def _supabase_base() -> str:
    return settings.supabase_url.rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "apikey": settings.supabase_secret_key,
        "Content-Type": "application/json",
    }


def signed_download_url(
    bucket: str,
    path: str,
    expires_in: int = 3600,
    *,
    retries: int = 2,
) -> str | None:
    """Mint a time-limited signed URL the browser can GET to download
    the object. Returns the absolute URL (https://…/object/sign/…)
    or None on failure.

    storage3's create_signed_url has been raising httpx
    RemoteProtocolError("Server disconnected") under HTTP/2; we POST
    the same endpoint over HTTP/1.1 with a single retry."""
    if not path:
        return None
    base = _supabase_base()
    url = f"{base}/storage/v1/object/sign/{bucket}/{path}"

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                http2=False,
                timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0),
            ) as client:
                r = client.post(
                    url,
                    json={"expiresIn": int(expires_in)},
                    headers=_headers(),
                )
            if r.status_code >= 400:
                log.warning(
                    "signed_download_url non-2xx (attempt %d) bucket=%s path=%s status=%s body=%s",
                    attempt + 1,
                    bucket,
                    path,
                    r.status_code,
                    r.text[:200],
                )
                continue
            data: dict[str, Any] = r.json()
            rel = data.get("signedURL") or data.get("signed_url") or data.get("signedUrl")
            if not rel:
                log.warning("signed_download_url no URL in body: %s", data)
                return None
            # Supabase returns a relative path like /object/sign/...; prepend base.
            if rel.startswith("http://") or rel.startswith("https://"):
                return rel
            if not rel.startswith("/"):
                rel = "/" + rel
            return f"{base}/storage/v1{rel}"
        except Exception as e:
            last_err = e
            log.warning(
                "signed_download_url threw (attempt %d) bucket=%s path=%s err=%s",
                attempt + 1,
                bucket,
                path,
                e,
            )
            continue

    if last_err:
        log.exception("signed_download_url exhausted retries", exc_info=last_err)
    return None


def signed_upload_url(
    bucket: str,
    path: str,
    *,
    retries: int = 2,
) -> dict[str, str] | None:
    """Mint a one-shot signed URL the client can PUT directly to —
    used by /houses/{id}/video/upload-url. Returns
    {signed_url, token, path} or None on failure."""
    base = _supabase_base()
    url = f"{base}/storage/v1/object/upload/sign/{bucket}/{path}"

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                http2=False,
                timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0),
            ) as client:
                r = client.post(url, headers=_headers())
            if r.status_code >= 400:
                log.warning(
                    "signed_upload_url non-2xx (attempt %d) bucket=%s path=%s status=%s body=%s",
                    attempt + 1,
                    bucket,
                    path,
                    r.status_code,
                    r.text[:200],
                )
                continue
            data: dict[str, Any] = r.json()
            rel = data.get("url") or data.get("signedURL")
            token = data.get("token") or ""
            if not rel:
                log.warning("signed_upload_url no URL in body: %s", data)
                return None
            if rel.startswith("/"):
                rel = f"{base}/storage/v1{rel}"
            return {"signed_url": rel, "token": token, "path": path}
        except Exception as e:
            last_err = e
            log.warning(
                "signed_upload_url threw (attempt %d) bucket=%s path=%s err=%s",
                attempt + 1,
                bucket,
                path,
                e,
            )
            continue

    if last_err:
        log.exception("signed_upload_url exhausted retries", exc_info=last_err)
    return None
