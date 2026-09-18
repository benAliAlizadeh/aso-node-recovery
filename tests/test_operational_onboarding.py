from pathlib import Path

from app.bot.formatters import format_nodes, format_providers
from app.registry.service import RegistryReadiness


ROOT = Path(__file__).resolve().parents[1]


def test_registry_readiness_requires_provider_node_vps_and_credentials() -> None:
    assert not RegistryReadiness(1, 1, 0, 1).ready
    assert not RegistryReadiness(1, 1, 1, 0).ready
    assert RegistryReadiness(1, 1, 1, 1).ready


def test_empty_bot_views_explain_onboarding() -> None:
    assert "./asoctl setup" in format_nodes([])
    assert "./asoctl setup" in format_providers([])


def test_quick_installer_health_precedes_telegram_start_and_is_visible() -> None:
    source = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
    start = source.index('log "Starting API and worker')
    health = source.index("wait_for_health", start)
    telegram = source.index('log "Starting Telegram bot profile."', start)
    assert health < telegram
    assert "Still waiting for API health" in source
    assert "verify_telegram_bot" in source
    assert "wait_for_bot" in source


def test_asoctl_exposes_registry_and_safe_monitoring_workflow() -> None:
    source = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    assert "setup_registry" in source
    assert "registry_cli.py smart-add-provider" in source
    assert "registry_cli.py smart-preview-node" in source
    assert "registry_cli.py smart-add-node" in source
    assert "monitoring-dry-run" in source
    assert "set_env ASO_DRY_RUN true" in source
    assert "set_env ASO_REPLACEMENT_WORKER_ENABLED false" in source
    assert "set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION false" in source


def test_registry_setup_is_documented_as_non_destructive() -> None:
    source = (ROOT / "app" / "registry" / "service.py").read_text(encoding="utf-8")
    assert "never calls provider APIs" in source
    assert "never mutates the Master panel" in source
    assert "never starts a replacement" in source
