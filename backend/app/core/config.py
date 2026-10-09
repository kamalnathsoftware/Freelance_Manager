from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Freelance Manager"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://fm:fm@localhost:5432/fm"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = "change-me-in-production-please-32-bytes"
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt tokens/credentials at rest.
    encryption_key: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: list[str] = ["http://localhost:3000"]
    web_base_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "no-reply@freelancemanager.local"

    google_client_id: str = ""
    google_client_secret: str = ""
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    sentry_dsn: str = ""
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
