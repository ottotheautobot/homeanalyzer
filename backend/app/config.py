from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_secret_key: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    sentry_dsn: str = ""
    environment: str = "development"

    frontend_url: str = "http://localhost:3000"

    meetingbaas_api_key: str = ""
    meetingbaas_webhook_secret: str = ""

    # Zoom Meeting SDK credentials (App Type = General, Embed/Meeting SDK on).
    # Required as of March 2 2026 for bots joining the developer's OWN Zoom
    # account (PMR or otherwise). Skips the OBF flow that's required for
    # external customer meetings — fits our single-user MVP perfectly.
    zoom_sdk_id: str = ""
    zoom_sdk_secret: str = ""

    deepgram_api_key: str = ""

    # Public base URL for this backend, used to build webhook + streaming URLs
    # we hand to Meeting BaaS. Set in Railway env to the Railway-issued URL.
    backend_url: str = "http://localhost:8000"
    # Shared secret used to sign per-bot streaming URL tokens so unauthenticated
    # WebSocket connections from the open internet can't impersonate a bot.
    streaming_url_secret: str = "dev-only-change-me"


settings = Settings()
