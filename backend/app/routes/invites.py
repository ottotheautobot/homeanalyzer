"""Tour invites: owner sends a magic link, recipient lands authed and is
added to tour_participants for that tour.

Magic-link delivery uses Supabase's admin invite (creates the user account
if it doesn't exist) with the redirect pointing at our /invite/{token}
page, which calls the accept endpoint here.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["invites"])
log = logging.getLogger(__name__)

INVITE_TTL_DAYS = 14
ALLOWED_ROLES = {"buyer", "partner", "agent"}


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

    redirect_to = f"{settings.frontend_url.rstrip('/')}/invite/{token}"
    try:
        sb.auth.admin.invite_user_by_email(
            body.email, {"redirect_to": redirect_to}
        )
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "registered" in msg or "exists" in msg:
            # User exists — send a magic link instead so they get a click-through.
            try:
                sb.auth.sign_in_with_otp(
                    {"email": body.email, "options": {"email_redirect_to": redirect_to}}
                )
            except Exception:
                log.exception("OTP send failed for %s", body.email)
        else:
            log.exception("invite send failed for %s on tour %s", body.email, tour_id)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Could not send invite: {e}"
            ) from e

    log.info("invite created for %s tour=%s role=%s", body.email, tour_id, body.role)
    return InviteOut(**invite)


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
