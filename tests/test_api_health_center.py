from __future__ import annotations

from pathlib import Path

from app.diagnostics import ApiHealthReport, ApiHealthResult, ApiHealthService, ApiHealthStatus
from app.master.types import MasterNode

ROOT = Path(__file__).resolve().parents[1]


def test_health_center_source_is_read_only() -> None:
    source = (ROOT / "app" / "diagnostics" / "service.py").read_text(encoding="utf-8")
    for forbidden in (
        ".create_server(",
        ".delete_server(",
        ".reboot_server(",
        ".update_node(",
        ".trigger_replacement(",
        ".resume_job(",
    ):
        assert forbidden not in source
    assert "probe_access()" in source
    assert 'text("SELECT 1")' in source
    assert "/getMe" in source


def test_health_ui_contains_status_latency_and_read_only_copy() -> None:
    source = (ROOT / "app" / "bot" / "health_ui.py").read_text(encoding="utf-8")
    assert "❤️ API Health Center" in source
    assert "latency_ms" in source
    assert "Read-only diagnostics only" in source
    assert "🔄 Refresh All" in source


def test_health_center_node_url_preserves_master_scheme_port_and_path() -> None:
    master = MasterNode(
        id=7,
        name="n",
        remark="",
        scheme="https",
        address="node.example.com",
        port=2053,
        base_path="/secret/",
        has_api_token=True,
        enable=True,
        allow_private_address=False,
        tls_verify_mode="verify",
        pinned_cert_sha256="",
        inbound_sync_mode="all",
        inbound_tags=(),
        outbound_tag="",
        guid="g",
        status="online",
        xray_state="running",
    )
    assert ApiHealthService._node_access_url(master) == "https://node.example.com:2053/secret"


def test_health_center_safe_error_is_bounded() -> None:
    text = ApiHealthService._safe_error(RuntimeError("x" * 500))
    assert len(text) <= 220
    assert text.startswith("RuntimeError:")


def test_api_health_is_available_from_inline_menu_and_command() -> None:
    source = (ROOT / "app" / "bot" / "application.py").read_text(encoding="utf-8")
    assert 'callback_data="m.health"' in source
    assert 'CommandHandler("apihealth", self.api_health)' in source
    assert 'BotCommand("apihealth", "Check external API health")' in source
    assert "self.health_ui.register(application)" in source
