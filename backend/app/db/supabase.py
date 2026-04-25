from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache(maxsize=1)
def supabase() -> Client:
    """Service-role client. Bypasses RLS. Never expose to browser clients."""
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
    return create_client(settings.supabase_url, settings.supabase_secret_key)
