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
        env_ignore_empty=True,
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # Safety invariant: destructive actions remain disabled unless a later explicitly authorized
    # production configuration changes this value.
    dry_run: bool = True
    allow_real_infrastructure_mutation: bool = False
    # Independent kill switch for the only destructive action against the current/old VPS.
    allow_old_vps_deletion: bool = False
    old_vps_delete_confirmation: str = ""
    max_replacement_attempts: int = Field(default=5, ge=1, le=50)
    max_temporary_servers: int = Field(default=3, ge=1, le=100)
    max_concurrent_replacements: int = Field(default=2, ge=1, le=100)

    database_url: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_bot_enabled: bool = False
    telegram_authorized_user_ids: tuple[int, ...] = ()
    telegram_callback_secret: SecretStr | None = None
    telegram_notification_chat_id: int | None = None
    telegram_poll_timeout_seconds: int = Field(default=30, ge=1, le=60)
    telegram_progress_interval_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    telegram_notification_interval_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    api_health_timeout_seconds: float = Field(default=12.0, ge=1.0, le=60.0)
    api_health_max_concurrency: int = Field(default=8, ge=1, le=32)
    hetzner_api_token: SecretStr | None = None
    linode_api_token: SecretStr | None = None
    master_3xui_base_url: str | None = None
    master_3xui_api_token: SecretStr | None = None
    master_3xui_username: str | None = None
    master_3xui_password: SecretStr | None = None
    master_3xui_verify_tls: bool = True
    master_3xui_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)

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

    # Provider / provisioning adapters. Values are intentionally generic; actual region/type/image
    # choices are supplied by the later replacement policy, not hard-coded here.
    hetzner_api_base_url: str = "https://api.hetzner.cloud/v1"
    linode_api_base_url: str = "https://api.linode.com/v4"
    provisioning_timeout_seconds: float = Field(default=300.0, ge=30.0, le=3600.0)
    provisioning_poll_interval_seconds: float = Field(default=3.0, ge=0.5, le=60.0)
    provider_reconcile_grace_seconds: int = Field(default=30, ge=0, le=900)

    # Persisted replacement orchestration. The worker remains opt-in; DRY_RUN remains the default.
    replacement_worker_enabled: bool = False
    replacement_worker_interval_seconds: int = Field(default=15, ge=5, le=3600)
    worker_scheduler_enabled: bool = False
    replacement_ip_check_port: int = Field(default=22, ge=1, le=65535)
    replacement_job_lease_seconds: int = Field(default=1800, ge=30, le=3600)
    replacement_emergency_stop: bool = True
    runtime_secret_dir: str = ".runtime-secrets"

    # Backup/restore. Restore remains independently disabled by default because it is destructive.
    backup_dir: str = ".backups"
    backup_retention_count: int = Field(default=14, ge=1, le=365)
    allow_database_restore: bool = False

    # SSH / 3X-UI deployment defaults. Strict host-key verification remains enabled by default.
    ssh_ready_timeout_seconds: float = Field(default=180.0, ge=10.0, le=1800.0)
    ssh_poll_interval_seconds: float = Field(default=3.0, ge=0.5, le=60.0)
    ssh_verify_host_key: bool = True
    ssh_known_hosts_path: str | None = None
    three_xui_version: str | None = None
    three_xui_verify_tls: bool = True

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if self.check_host_min_success_nodes > self.check_host_max_nodes:
            raise ValueError("check_host_min_success_nodes cannot exceed check_host_max_nodes")

        if self.telegram_bot_enabled:
            if self.telegram_bot_token is None:
                raise ValueError("telegram_bot_token is required when telegram_bot_enabled=true")
            if not self.telegram_authorized_user_ids:
                raise ValueError(
                    "telegram_authorized_user_ids cannot be empty when Telegram is enabled"
                )
            if self.telegram_callback_secret is None:
                raise ValueError(
                    "telegram_callback_secret is required when Telegram is enabled"
                )
            if len(self.telegram_callback_secret.get_secret_value()) < 32:
                raise ValueError("telegram_callback_secret must be at least 32 characters")

        if self.allow_old_vps_deletion:
            if self.dry_run:
                raise ValueError("old VPS deletion cannot be enabled while DRY_RUN=true")
            if not self.allow_real_infrastructure_mutation:
                raise ValueError(
                    "old VPS deletion requires ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true"
                )
            if self.old_vps_delete_confirmation != "DELETE_ONLY_VERIFIED_OLD_VPS":
                raise ValueError(
                    "old VPS deletion requires exact confirmation phrase "
                    "DELETE_ONLY_VERIFIED_OLD_VPS"
                )

        if self.environment == "production":
            if not self.ssh_verify_host_key:
                raise ValueError("production requires SSH host-key verification")
            if not self.three_xui_verify_tls:
                raise ValueError("production requires 3X-UI TLS verification")
            if not self.master_3xui_verify_tls:
                raise ValueError("production requires Master 3X-UI TLS verification")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
