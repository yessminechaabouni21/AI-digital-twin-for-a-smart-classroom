"""Centralized application settings, loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://twin:twin@localhost:5432/digital_twin"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
