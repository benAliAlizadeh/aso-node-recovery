from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(
        (ROOT / "VERSION").read_text().strip()
        in {
            "1.0.1-quick-installer",
            "1.0.2-safety-hardening",
            "1.0.3-installer-permissions-hotfix",
            "1.0.4-runtime-volume-capability-hotfix",
            "1.0.5-postgres-auth-hotfix",
        "1.0.6-operational-onboarding",
        "1.0.7-health-readiness-hotfix",
        "1.1.0-smart-onboarding",
        "1.2.0-telegram-registry-ui",
        "1.3.0-api-health-center",
        "1.4.0-runtime-controls", "1.5.0-force-repair-hardening",
        },
        "bad VERSION",
    )
    for relative in (
        "install.sh",
        "asoctl",
        "scripts/quick_install.sh",
        "scripts/asoctl.sh",
        "docs/QUICK_INSTALL.md",
        "tests/test_quick_install_assets.py",
    ):
        path = ROOT / relative
        require(path.is_file(), f"missing {relative}")

    installer = (ROOT / "scripts/quick_install.sh").read_text()
    require("set_env ASO_DRY_RUN true" in installer, "installer must force DRY_RUN")
    require(
        "set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION false" in installer,
        "installer must force mutation guard off",
    )
    require(
        "set_env ASO_REPLACEMENT_WORKER_ENABLED false" in installer,
        "installer must leave replacement worker disabled",
    )
    require("apt-get remove" not in installer and "apt-get purge" not in installer,
            "installer must not auto-remove host packages")

    ctl = (ROOT / "scripts/asoctl.sh").read_text()
    require("down -v" not in ctl and "down --volumes" not in ctl, "asoctl must preserve volumes")
    print("Patch 06 quick-installer validation: PASS")


if __name__ == "__main__":
    main()
