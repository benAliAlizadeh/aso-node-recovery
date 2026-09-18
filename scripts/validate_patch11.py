from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert (ROOT / "VERSION").read_text().strip() in {
        "1.0.6-operational-onboarding",
        "1.0.7-health-readiness-hotfix",
        "1.1.0-smart-onboarding",
    }
    assert 'version = "1.1.0"' in (ROOT / "pyproject.toml").read_text()

    installer = (ROOT / "scripts" / "quick_install.sh").read_text()
    start = installer.index('log "Starting API and worker')
    assert installer.index("wait_for_health", start) < installer.index(
        'log "Starting Telegram bot profile."', start
    )
    assert "verify_telegram_bot" in installer
    assert "wait_for_bot" in installer
    assert "Still waiting for API health" in installer

    asoctl = (ROOT / "scripts" / "asoctl.sh").read_text()
    for token in (
        "setup_registry",
        "telegram-check",
        "monitoring-dry-run",
        "set_env ASO_DRY_RUN true",
        "set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION false",
        "set_env ASO_REPLACEMENT_WORKER_ENABLED false",
    ):
        assert token in asoctl
    assert (
        "registry_cli.py add-provider" in asoctl
        or "registry_cli.py smart-add-provider" in asoctl
    )
    assert (
        "registry_cli.py add-node" in asoctl
        or "registry_cli.py smart-add-node" in asoctl
    )

    registry = (ROOT / "app" / "registry" / "service.py").read_text()
    assert "never calls provider APIs" in registry
    assert "never mutates the Master panel" in registry
    assert "never starts a replacement" in registry

    bot = (ROOT / "app" / "bot" / "application.py").read_text()
    assert "m.status" in bot
    assert "set_my_commands" in bot
    assert "./asoctl setup" in bot

    assert (ROOT / "scripts" / "registry_cli.py").is_file()
    assert (ROOT / "scripts" / "telegram_probe.py").is_file()
    assert (ROOT / "docs" / "ONBOARDING.md").is_file()
    print("Patch 11 operational onboarding validation: PASS")


if __name__ == "__main__":
    main()
