"""Tour invites: owner sends a magic link, recipient lands authed and is
added to tour_participants for that tour.

Magic-link delivery uses Supabase's admin invite (creates the user account
if it doesn't exist) with the redirect pointing at our /invite/{token}
page, which calls the accept endpoint here.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import resend
import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["invites"])
log = logging.getLogger(__name__)

INVITE_TTL_DAYS = 14
ALLOWED_ROLES = {"buyer", "partner", "agent", "friend_family"}


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "partner"


class InviteOut(BaseModel):
    id: str
    tour_id: str
    email: str
    role: str | None
    expires_at: datetime
    accepted_at: datetime | None


class AcceptResult(BaseModel):
    tour_id: str


def _require_owner(tour_id: str, user_id: str) -> dict:
    sb = supabase()
    res = sb.table("tours").select("*").eq("id", tour_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tour not found")
    tour = res.data[0]
    if tour["owner_user_id"] != user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the tour owner can invite"
        )
    return tour


@router.post(
    "/tours/{tour_id}/invite",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    tour_id: str,
    body: InviteCreate,
    user: AuthUser = Depends(current_user),
) -> InviteOut:
    if body.role not in ALLOWED_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"role must be one of {sorted(ALLOWED_ROLES)}",
        )
    tour = _require_owner(tour_id, user.id)

    sb = supabase()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)

    invite_res = (
        sb.table("tour_invites")
        .insert(
            {
                "tour_id": tour_id,
                "email": body.email,
                "role": body.role,
                "token": token,
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
    )
    invite = invite_res.data[0]

    # Route through /auth/callback for PKCE code exchange, then to
    # /invite/{token} which auto-accepts. Even if Supabase strips the
    # ?next=, the per-request invite auto-claim sweep in db/users.py
    # picks them up on the next authed call.
    next_path = f"/invite/{token}"
    redirect_to = (
        f"{settings.frontend_url.rstrip('/')}/auth/callback"
        f"?next={quote(next_path, safe='/')}"
    )

    # Generate the one-tap login URL via Supabase admin (no email sent).
    # Try invite first (creates user); fall back to magiclink if user exists.
    action_link: str | None = None
    try:
        link = sb.auth.admin.generate_link(
            {
                "type": "invite",
                "email": body.email,
                "options": {"redirect_to": redirect_to},
            }
        )
        action_link = link.properties.action_link
    except Exception as e:
        log.info("generate_link 'invite' failed (likely existing user): %s", e)

    if not action_link:
        try:
            link = sb.auth.admin.generate_link(
                {
                    "type": "magiclink",
                    "email": body.email,
                    "options": {"redirect_to": redirect_to},
                }
            )
            action_link = link.properties.action_link
        except Exception as e:
            log.exception("magiclink generation failed for %s", body.email)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Could not generate invite link: {e}",
            ) from e

    _send_invite_email(
        to=body.email,
        owner_name=_owner_label(user.id),
        tour_name=tour["name"],
        action_link=action_link,
    )

    log.info("invite created for %s tour=%s role=%s", body.email, tour_id, body.role)
    return InviteOut(**invite)


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


def _send_invite_email(
    *, to: str, owner_name: str, tour_name: str, action_link: str
) -> None:
    if not settings.resend_api_key:
        log.warning("RESEND_API_KEY not set — invite email skipped")
        return
    subject = f"{owner_name} invited you to a HomeAnalyzer tour"
    text = (
        f"{owner_name} invited you to the tour \"{tour_name}\" on HomeAnalyzer.\n\n"
        f"Open the tour in one tap:\n{action_link}\n\n"
        "This link logs you in automatically — no password needed."
    )
    html = f"""
<!doctype html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#18181b;line-height:1.55;max-width:520px;margin:0 auto;padding:24px;">
  <h2 style="margin:0 0 8px;font-size:20px;">{owner_name} invited you to a tour</h2>
  <p style="margin:0 0 24px;color:#52525b;">
    <strong>{tour_name}</strong> on HomeAnalyzer
  </p>
  <p style="margin:0 0 24px;">
    <a href="{action_link}"
       style="display:inline-block;padding:12px 24px;background:#5b50e8;color:#fff;text-decoration:none;border-radius:10px;font-weight:600;">
      Open the tour
    </a>
  </p>
  <p style="margin:0;color:#71717a;font-size:13px;">
    Tapping the button logs you in automatically — no password needed.
  </p>
</body>
</html>
""".strip()

    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            }
        )
        log.info("invite email sent to %s", to)
    except Exception as e:
        log.exception("invite email send failed for %s", to)
        sentry_sdk.capture_exception(e)


@router.get("/tours/{tour_id}/invites", response_model=list[InviteOut])
def list_invites(
    tour_id: str, user: AuthUser = Depends(current_user)
) -> list[InviteOut]:
    _require_owner(tour_id, user.id)
    sb = supabase()
    res = (
        sb.table("tour_invites")
        .select("*")
        .eq("tour_id", tour_id)
        .order("expires_at", desc=True)
        .execute()
    )
    return [InviteOut(**i) for i in res.data or []]


@router.delete("/tours/{tour_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invite(
    tour_id: str,
    invite_id: str,
    user: AuthUser = Depends(current_user),
):
    _require_owner(tour_id, user.id)
    sb = supabase()
    sb.table("tour_invites").delete().eq("id", invite_id).eq(
        "tour_id", tour_id
    ).execute()
    from fastapi import Response

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invites/{token}/accept", response_model=AcceptResult)
def accept_invite(
    token: str, user: AuthUser = Depends(current_user)
) -> AcceptResult:
    sb = supabase()
    res = (
        sb.table("tour_invites")
        .select("*")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    invite = res.data[0]

    expires_at = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "Invite expired")

    if invite["email"].lower() != user.email.lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This invite was sent to a different email ({invite['email']})",
        )

    sb.table("tour_participants").upsert(
        {
            "tour_id": invite["tour_id"],
            "user_id": user.id,
            "role": invite["role"],
            "joined_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="tour_id,user_id",
    ).execute()

    if not invite.get("accepted_at"):
        sb.table("tour_invites").update(
            {"accepted_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", invite["id"]).execute()

    return AcceptResult(tour_id=invite["tour_id"])
