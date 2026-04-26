from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.supabase import supabase
from app.deps import AuthUser, current_user

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    id: str
    email: str
    name: str | None
    default_zoom_url: str | None


@router.get("/me", response_model=MeOut)
def get_me(user: AuthUser = Depends(current_user)) -> MeOut:
    sb = supabase()
    res = (
        sb.table("users")
        .select("id, email, name, default_zoom_url")
        .eq("id", user.id)
        .limit(1)
        .execute()
    )
    row = res.data[0] if res.data else {"id": user.id, "email": user.email}
    return MeOut(
        id=row["id"],
        email=row["email"],
        name=row.get("name"),
        default_zoom_url=row.get("default_zoom_url"),
    )
