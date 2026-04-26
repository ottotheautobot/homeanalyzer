"""Transactional email notifications via Resend.

Currently sends a "tour starting" email to every tour participant when the
owner taps Start Tour on a house. Skipped silently if RESEND_API_KEY is
unset so nothing in dev/test is blocked on email setup.
"""

import logging

import resend
import sentry_sdk

from app.config import settings
from app.db.supabase import supabase

log = logging.getLogger(__name__)


def _participant_emails(tour_id: str, exclude_user_id: str | None) -> list[str]:
    """Return participant emails for a tour, optionally excluding one user."""
    sb = supabase()
    # Two-step join: tour_participants -> users
    parts = (
        sb.table("tour_participants")
        .select("user_id")
        .eq("tour_id", tour_id)
        .execute()
    )
    user_ids = [
        p["user_id"] for p in (parts.data or []) if p["user_id"] != exclude_user_id
    ]
    if not user_ids:
        return []
    users = (
        sb.table("users")
        .select("id, email")
        .in_("id", user_ids)
        .execute()
    )
    return [u["email"] for u in (users.data or []) if u.get("email")]


def _owner_label(owner_user_id: str) -> str:
    sb = supabase()
    res = (
        sb.table("users")
        .select("name, email")
        .eq("id", owner_user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return "Someone"
    row = res.data[0]
    return row.get("name") or row.get("email") or "Someone"


def send_tour_started_email(
    *,
    tour_id: str,
    tour_name: str,
    owner_user_id: str,
    house_id: str,
    house_address: str,
    zoom_url: str,
) -> None:
    """Notify every tour participant (other than the owner) that a tour
    started on a specific house. Includes the Zoom URL and a deep link to
    the live observation feed in the app."""
    if not settings.resend_api_key:
        log.info("RESEND_API_KEY not set — skipping tour-started notification")
        return

    recipients = _participant_emails(tour_id, exclude_user_id=owner_user_id)
    if not recipients:
        log.info("no recipients for tour %s; nothing to send", tour_id)
        return

    owner = _owner_label(owner_user_id)
    app_url = (
        f"{settings.frontend_url.rstrip('/')}/tours/{tour_id}/houses/{house_id}"
    )

    subject = f"Tour starting: {house_address}"
    text = (
        f"{owner} just started touring {house_address} as part of \"{tour_name}\".\n\n"
        f"Join the Zoom: {zoom_url}\n\n"
        f"Or watch observations populate live in the app:\n{app_url}\n"
    )
    html = f"""
<!doctype html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#18181b;line-height:1.55;max-width:520px;margin:0 auto;padding:24px;">
  <h2 style="margin:0 0 12px;font-size:18px;">{owner} is touring a house</h2>
  <p style="margin:0 0 20px;color:#52525b;">
    {house_address} &middot; tour <em>{tour_name}</em>
  </p>
  <p style="margin:0 0 20px;">
    <a href="{zoom_url}"
       style="display:inline-block;padding:10px 16px;background:#2b7fff;color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">
      Join the Zoom
    </a>
  </p>
  <p style="margin:0 0 8px;">
    Or watch observations populate live in the app:
  </p>
  <p style="margin:0;">
    <a href="{app_url}" style="color:#2b7fff;">{app_url}</a>
  </p>
</body>
</html>
""".strip()

    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": recipients,
                "subject": subject,
                "html": html,
                "text": text,
            }
        )
        log.info(
            "tour-started email sent to %d recipient(s) for tour %s",
            len(recipients),
            tour_id,
        )
    except Exception as e:
        log.exception("tour-started email send failed for tour %s", tour_id)
        sentry_sdk.capture_exception(e)
