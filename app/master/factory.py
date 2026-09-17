from __future__ import annotations

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.master.client import Master3XUiClient


class Master3XUiClientFactory:
    @staticmethod
    def create(settings: Settings) -> Master3XUiClient:
        if not settings.master_3xui_base_url:
            raise ConfigurationError("ASO_MASTER_3XUI_BASE_URL is required")
        if settings.master_3xui_api_token is None and (
            not settings.master_3xui_username or settings.master_3xui_password is None
        ):
            raise ConfigurationError(
                "configure ASO_MASTER_3XUI_API_TOKEN or master username/password"
            )
        return Master3XUiClient(
            settings.master_3xui_base_url,
            api_token=settings.master_3xui_api_token,
            username=settings.master_3xui_username,
            password=settings.master_3xui_password,
            verify_tls=settings.master_3xui_verify_tls,
            timeout_seconds=settings.master_3xui_timeout_seconds,
        )
