from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert (ROOT / "VERSION").read_text().strip() in {
        "1.0.3-installer-permissions-hotfix",
        "1.0.4-runtime-volume-capability-hotfix",
        "1.0.5-postgres-auth-hotfix",
        "1.0.6-operational-onboarding",
        "1.0.7-health-readiness-hotfix",
        "1.1.0-smart-onboarding",
        "1.2.0-telegram-registry-ui",
        "1.3.0-api-health-center",
    }
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    installer = (ROOT / "scripts" / "quick_install.sh").read_text()
    security = (ROOT / "scripts" / "security_review.py").read_text()
    assert "runtime-init:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "chmod 0700 /var/lib/aso/secrets /var/lib/aso/backups" in compose
    assert "chown aso:aso /var/lib/aso/secrets /var/lib/aso/backups" in compose
    assert "compose run --rm --no-deps runtime-init" in installer
    assert "runtime secret directory is owned by the runtime user" in security
    assert "runtime backup directory is owner-only" in security
    print("Patch 08 validation: PASS")


if __name__ == "__main__":
    main()
