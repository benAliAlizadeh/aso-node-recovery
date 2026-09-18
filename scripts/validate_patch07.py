from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings


def main() -> None:
    assert (ROOT / "VERSION").read_text().strip() in {
        "1.0.2-safety-hardening",
        "1.0.3-installer-permissions-hotfix",
        "1.0.4-runtime-volume-capability-hotfix",
        "1.0.5-postgres-auth-hotfix",
        "1.0.6-operational-onboarding",
    }
    settings = Settings()
    assert settings.dry_run is True
    assert settings.allow_real_infrastructure_mutation is False
    assert settings.allow_old_vps_deletion is False
    assert settings.replacement_emergency_stop is True

    orchestrator = (ROOT / "app" / "replacement" / "orchestrator.py").read_text()
    assert "allow_old_vps_deletion" in orchestrator
    assert "provider IP does not match registry identity" in orchestrator
    assert "deterministic replacement identity" in orchestrator
    assert "await adapter.delete_server(old_server_id)" in orchestrator

    installer = (ROOT / "scripts" / "quick_install.sh").read_text()
    assert "set_env ASO_ALLOW_OLD_VPS_DELETION false" in installer
    assert "set_env ASO_REPLACEMENT_EMERGENCY_STOP true" in installer
    assert "set_env ASO_ALLOW_OLD_VPS_DELETION true" not in installer
    print("Patch 07 destructive-operation safety hardening: PASS")


if __name__ == "__main__":
    main()
