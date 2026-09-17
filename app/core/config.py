from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration."""

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

    # Safety invariant: destructive actions remain disabled unless a later explicitly authorized
    # production configuration changes this value.
    dry_run: bool = True
    max_replacement_attempts: int = Field(default=5, ge=1, le=50)
    max_temporary_servers: int = Field(default=3, ge=1, le=100)
    max_concurrent_replacements: int = Field(default=2, ge=1, le=100)

    database_url: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    hetzner_api_token: SecretStr | None = None
    linode_api_token: SecretStr | None = None
    master_3xui_base_url: str | None = None
    master_3xui_username: str | None = None
    master_3xui_password: SecretStr | None = None

    # Monitoring / Check-Host. Explicit nodes win; otherwise nodes are discovered from the official
    # node list using check_host_country_code.
    monitoring_scheduler_enabled: bool = False
    check_interval_seconds: int = Field(default=60, ge=10, le=86400)
    failure_threshold: int = Field(default=3, ge=1, le=100)
    recovery_threshold: int = Field(default=2, ge=1, le=100)
    check_host_base_url: str = "https://check-host.net"
    check_host_country_code: str = Field(default="ir", min_length=2, max_length=2)
    check_host_nodes: tuple[str, ...] = ()
    check_host_max_nodes: int = Field(default=5, ge=1, le=25)
    check_host_min_success_nodes: int = Field(default=3, ge=1, le=25)
    check_host_poll_interval_seconds: float = Field(default=1.0, ge=0.2, le=30.0)
    check_host_result_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    monitoring_lease_seconds: int = Field(default=45, ge=5, le=600)

    @model_validator(mode="after")
    def validate_monitoring_thresholds(self) -> "Settings":
        if self.check_host_min_success_nodes > self.check_host_max_nodes:
            raise ValueError("check_host_min_success_nodes cannot exceed check_host_max_nodes")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
