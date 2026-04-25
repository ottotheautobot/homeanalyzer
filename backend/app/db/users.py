from app.db.supabase import supabase


def ensure_user(auth_id: str, email: str, name: str | None = None) -> dict:
    """Upsert a row in public.users keyed on the Supabase auth UUID."""
    payload = {"id": auth_id, "email": email}
    if name is not None:
        payload["name"] = name
    res = (
        supabase()
        .table("users")
        .upsert(payload, on_conflict="id")
        .execute()
    )
    return res.data[0]
