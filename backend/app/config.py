from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    sentry_dsn: str = ""
    environment: str = "development"

    frontend_url: str = "http://localhost:3000"

    meetingbaas_api_key: str = ""
    meetingbaas_webhook_secret: str = ""


settings = Settings()
