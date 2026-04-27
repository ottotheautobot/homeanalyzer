from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    id: str
    email: str
    name: str | None
    default_zoom_url: str | None


class MePatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    default_zoom_url: str | None = Field(default=None, max_length=2000)


def _read_me(user_id: str, email: str) -> MeOut:
    sb = supabase()
    res = (
        sb.table("users")
        .select("id, email, name, default_zoom_url")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    row = res.data[0] if res.data else {"id": user_id, "email": email}
    return MeOut(
        id=row["id"],
        email=row["email"],
        name=row.get("name"),
        default_zoom_url=row.get("default_zoom_url"),
    )


@router.get("/me", response_model=MeOut)
def get_me(user: AuthUser = Depends(current_user)) -> MeOut:
    return _read_me(user.id, user.email)


@router.patch("/me", response_model=MeOut)
def patch_me(payload: MePatch, user: AuthUser = Depends(current_user)) -> MeOut:
    """Update name + default Zoom URL. Empty string = clear the value."""
    update: dict = {}
    if payload.name is not None:
        cleaned = payload.name.strip()
        update["name"] = cleaned or None
    if payload.default_zoom_url is not None:
        cleaned = payload.default_zoom_url.strip()
        if cleaned and not (
            cleaned.startswith("https://")
            or cleaned.startswith("http://")
            or cleaned.startswith("zoommtg:")
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Zoom URL must start with https:// or zoommtg:",
            )
        update["default_zoom_url"] = cleaned or None
    if update:
        sb = supabase()
        sb.table("users").update(update).eq("id", user.id).execute()
    return _read_me(user.id, user.email)
