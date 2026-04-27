import logging
from datetime import datetime, timezone

from app.db.supabase import supabase

log = logging.getLogger(__name__)


def ensure_user(auth_id: str, email: str, name: str | None = None) -> dict:
    """Upsert a row in public.users keyed on the Supabase auth UUID, then
    auto-accept any pending tour invites for this email. The invite flow's
    /invite/{token} acceptance page is the primary path, but Supabase's
    magic-link redirect occasionally drops the `?next=` query param and
    invitees end up logged in without acceptance running. Running the sweep
    on every authed request guarantees they pick up their invites."""
    sb = supabase()
    payload = {"id": auth_id, "email": email}
    if name is not None:
        payload["name"] = name
    res = sb.table("users").upsert(payload, on_conflict="id").execute()
    user_row = res.data[0]

    try:
        _claim_pending_invites(auth_id, email)
    except Exception:
        log.exception("invite auto-claim failed for %s", email)

    return user_row


def _claim_pending_invites(user_id: str, email: str) -> None:
    sb = supabase()
    pending = (
        sb.table("tour_invites")
        .select("*")
        .ilike("email", email)
        .is_("accepted_at", "null")
        .execute()
    )
    if not pending.data:
        return

    now = datetime.now(timezone.utc).isoformat()
    for inv in pending.data:
        # Skip expired
        try:
            expires = datetime.fromisoformat(
                inv["expires_at"].replace("Z", "+00:00")
            )
            if expires < datetime.now(timezone.utc):
                continue
        except Exception:
            pass

        sb.table("tour_participants").upsert(
            {
                "tour_id": inv["tour_id"],
                "user_id": user_id,
                "role": inv["role"],
                "joined_at": now,
            },
            on_conflict="tour_id,user_id",
        ).execute()
        sb.table("tour_invites").update({"accepted_at": now}).eq(
            "id", inv["id"]
        ).execute()
        log.info(
            "auto-claimed invite for %s on tour %s", email, inv["tour_id"]
        )
