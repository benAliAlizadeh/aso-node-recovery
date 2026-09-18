from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert (ROOT / "VERSION").read_text().strip() in {
        "1.0.5-postgres-auth-hotfix",
        "1.0.6-operational-onboarding",
        "1.0.7-health-readiness-hotfix",
        "1.1.0-smart-onboarding",
        "1.2.0-telegram-registry-ui",
        "1.3.0-api-health-center",
        "1.4.0-runtime-controls",
    }
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    dockerfile = (ROOT / "docker" / "prod.Dockerfile").read_text()

    assert "runtime-init:" in compose
    assert 'user: "0:0"' in compose
    assert "- CHOWN" in compose
    assert "- FOWNER" in compose
    assert "- DAC_OVERRIDE" in compose
    assert 'network_mode: "none"' in compose
    assert "chown aso:aso /var/lib/aso/secrets /var/lib/aso/backups" in compose
    assert "chmod 0700 /var/lib/aso/secrets /var/lib/aso/backups" in compose
    assert "install -d -m 0700 -o aso -g aso" in dockerfile
    print("Patch 09 validation: PASS")


if __name__ == "__main__":
    main()
