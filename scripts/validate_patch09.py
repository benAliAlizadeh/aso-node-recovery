from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert (ROOT / "VERSION").read_text().strip() == "1.0.4-runtime-volume-capability-hotfix"
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
