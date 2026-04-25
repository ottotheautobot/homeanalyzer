from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.supabase import supabase
from app.db.users import ensure_user

security = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> AuthUser:
    """Verify the bearer JWT against Supabase and ensure a public.users row."""
    try:
        result = supabase().auth.get_user(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = getattr(result, "user", None)
    if not user or not user.id or not user.email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    ensure_user(user.id, user.email, (user.user_metadata or {}).get("name"))
    return AuthUser(id=user.id, email=user.email)
