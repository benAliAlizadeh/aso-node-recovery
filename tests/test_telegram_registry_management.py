from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.bot.callbacks import CallbackSigner
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]


def test_registry_ui_is_inline_and_exposes_expected_management_actions() -> None:
    source = (ROOT / "app" / "bot" / "registry_ui.py").read_text(encoding="utf-8")
    for text in (
        "➕ Add Provider",
        "➕ Add Node",
        "🧪 Test API",
        "🔑 Replace API Token",
        "🧪 Test All Access",
        "🔑 Replace Node API Token",
        "🔐 Replace SSH",
        "🗑 Remove from ASO",
    ):
        assert text in source
    assert "InlineKeyboardMarkup" in source
    assert "MessageHandler" in source


def test_registry_management_never_calls_provider_mutation_or_master_update() -> None:
    source = (ROOT / "app" / "registry" / "management.py").read_text(encoding="utf-8")
    forbidden = (
        ".create_server(",
        ".delete_server(",
        ".reboot_server(",
        ".update_node(",
    )
    for marker in forbidden:
        assert marker not in source


def test_registry_management_validates_before_token_swap() -> None:
    source = (ROOT / "app" / "registry" / "management.py").read_text(encoding="utf-8")
    provider_validate = source.index("await self.validate_provider_token(provider_type, candidate)")
    provider_swap = source.index("provider.credential_ref = staged_credential_ref")
    assert provider_validate < provider_swap

    node_validate = source.index("discovered = await self.discover_node(", source.index("async def replace_node_api_token"))
    node_swap = source.index("credential.api_token_ref = staged_ref", source.index("async def replace_node_api_token"))
    assert node_validate < node_swap


def test_signed_registry_confirmations_fit_telegram_callback_limit() -> None:
    signer = CallbackSigner(SecretStr("s" * 32))
    entity_id = uuid4()
    for action in ("px", "nx", "pc", "nc", "sc"):
        payload = signer.encode(action, entity_id, 100, now=6000)
        assert len(payload.encode("utf-8")) <= 64


def test_main_bot_delegates_nodes_and_providers_to_registry_ui() -> None:
    source = (ROOT / "app" / "bot" / "application.py").read_text(encoding="utf-8")
    assert "TelegramRegistryController" in source
    assert "await self.registry_ui.render_nodes" in source
    assert "await self.registry_ui.render_providers" in source
    assert "self.registry_ui.register(application)" in source
