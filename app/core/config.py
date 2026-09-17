from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration.

    External credentials are placeholders in Phase 1 and are intentionally not consumed by
    infrastructure clients yet.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ASO_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # Safety invariant: destructive actions are disabled unless a later, explicitly authorized
    # production configuration changes this value.
    dry_run: bool = True

    # Reserved for later phases. SecretStr prevents accidental plain-text representation.
    database_url: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    hetzner_api_token: SecretStr | None = None
    linode_api_token: SecretStr | None = None
    master_3xui_base_url: str | None = None
    master_3xui_username: str | None = None
    master_3xui_password: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
