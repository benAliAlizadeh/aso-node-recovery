from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.bot.callbacks import CallbackSigner
    from app.core.config import Settings
    from app.models import EventType

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version in {"1.0.0-production-release", "1.0.1-quick-installer", "1.0.2-safety-hardening"}

    required = [
        "app/control/service.py",
        "app/bot/application.py",
        "app/bot/auth.py",
        "app/bot/callbacks.py",
        "app/bot/notifier.py",
        "app/bot/runner.py",
        "app/backup/manager.py",
        "app/workers/scheduler.py",
        "app/workers/runner.py",
        "app/runtime.py",
        "docker/prod.Dockerfile",
        "docker-compose.prod.yml",
        "migrations/versions/20260917_0003_phase7_control_events.py",
        "docs/TELEGRAM.md",
        "docs/BACKUP_RESTORE.md",
        "docs/SECURITY.md",
        "docs/PRODUCTION.md",
        "docs/RELEASE.md",
    ]
    for relative in required:
        assert (ROOT / relative).is_file(), relative

    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.allow_real_infrastructure_mutation is False
    assert settings.telegram_bot_enabled is False
    assert settings.replacement_worker_enabled is False
    assert settings.worker_scheduler_enabled is False
    assert settings.allow_database_restore is False
    assert settings.ssh_verify_host_key is True
    assert settings.three_xui_verify_tls is True
    assert settings.master_3xui_verify_tls is True

    for expected in {
        EventType.CONTROL_ACTION,
        EventType.SYSTEM_PAUSED,
        EventType.SYSTEM_RESUMED,
        EventType.PROVIDER_UPDATED,
    }:
        assert expected.value

    signer = CallbackSigner(SecretStr("x" * 32))
    entity_id = uuid4()
    data = signer.encode("rc", entity_id, 123, now=6000)
    assert len(data.encode()) <= 64
    assert signer.verify(data, 123, now=6001).entity_id == entity_id

    bot_source = (ROOT / "app/bot/application.py").read_text(encoding="utf-8")
    for forbidden in ("ProviderFactory(", "NodeRepository(", "delete_server(", "CheckHostClient("):
        assert forbidden not in bot_source

    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "read_only: true" in compose
    assert "cap_drop:" in compose
    assert "no-new-privileges:true" in compose
    assert 'max-size: "10m"' in compose
    postgres_service = compose.split("\n  postgres:\n    image:", 1)[1]
    postgres_block = postgres_service.split("\nvolumes:\n", 1)[0]
    assert "\n    ports:" not in postgres_block

    replacement_source = (ROOT / "app/replacement/safety.py").read_text(encoding="utf-8")
    assert "final_health_verified_at" in replacement_source
    assert "master_verified_at" in replacement_source
    assert "deployment_verified_at" in replacement_source

    print("Patch 05 / Phase 7 validation: PASS")


if __name__ == "__main__":
    main()
