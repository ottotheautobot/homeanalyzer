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
    # Set to "false" in Railway env to skip svix signature verification on
    # MB webhooks. Temporary while we figure out v1's actual signing scheme.
    # Webhook URL is still per-bot and not internet-discoverable so the risk
    # is bounded for MVP single-user use.
    meetingbaas_verify_webhook: bool = True

    # Zoom Meeting SDK credentials (App Type = General, Embed/Meeting SDK on).
    # Required as of March 2 2026 for bots joining the developer's OWN Zoom
    # account (PMR or otherwise). Skips the OBF flow that's required for
    # external customer meetings — fits our single-user MVP perfectly.
    zoom_sdk_id: str = ""
    zoom_sdk_secret: str = ""

    # Zoom Server-to-Server OAuth (separate Marketplace app from the Meeting
    # SDK above). Required to programmatically end the host's meeting after
    # End Tour, so the Zoom call closes for all participants instead of
    # staying open until the host manually leaves.
    # Required scope on the S2S app: meeting:write:meeting:admin (or the
    # legacy meeting:write:admin). Empty = feature disabled, end_tour stops
    # the bot but leaves the Zoom meeting open.
    zoom_s2s_account_id: str = ""
    zoom_s2s_client_id: str = ""
    zoom_s2s_client_secret: str = ""

    deepgram_api_key: str = ""
    # Set true once MB confirms streaming.input works for our account. Until
    # then it costs tokens for nothing — MB establishes the WS but never
    # sends audio frames (verified with frame counters in streams.py).
    meetingbaas_enable_streaming: bool = False

    # Vision pipeline: extract scene-change frames from the bot's mp4 and
    # send to Haiku 4.5 for visual observations. ~$0.20-0.30 per 30-min tour.
    # Set false in Railway env to skip if costs bite.
    enable_vision_analysis: bool = True

    # Measured floor plan reconstruction (Modal worker, MASt3R/Depth Anything).
    # Default false — the pipeline is heavy and the schematic is fine for
    # most users. Flip on per-deploy when you want to test it.
    enable_measured_floorplan: bool = False
    modal_token_id: str = ""
    modal_token_secret: str = ""

    # Mapbox Directions Matrix API — used to compute drive-time commute
    # estimates from each house to each of the user's saved locations
    # (work, kids' school, etc.). Empty = falls back to as-the-crow-flies
    # haversine distance with no time estimate. Free tier: 100k matrix
    # requests/month, each request up to 25x25 origins-destinations.
    mapbox_api_token: str = ""

    # Resend transactional email — used to notify tour participants when a
    # tour starts on a house. Skipped silently if not set.
    resend_api_key: str = ""
    resend_from_email: str = "Tour Notes <onboarding@resend.dev>"

    # Public base URL for this backend, used to build webhook + streaming URLs
    # we hand to Meeting BaaS. Set in Railway env to the Railway-issued URL.
    backend_url: str = "http://localhost:8000"
    # Shared secret used to sign per-bot streaming URL tokens so unauthenticated
    # WebSocket connections from the open internet can't impersonate a bot.
    streaming_url_secret: str = "dev-only-change-me"


settings = Settings()
