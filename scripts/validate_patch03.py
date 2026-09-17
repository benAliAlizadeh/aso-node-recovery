from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.providers import DryRunProvider


REQUIRED_FILES = {
    "app/core/secrets.py",
    "app/providers/base.py",
    "app/providers/hetzner.py",
    "app/providers/linode.py",
    "app/providers/dry_run.py",
    "app/providers/factory.py",
    "app/providers/provisioning.py",
    "app/providers/manager.py",
    "app/deployment/ssh.py",
    "app/deployment/os_detection.py",
    "app/deployment/installer.py",
    "app/deployment/node_api.py",
    "app/deployment/state.py",
    "app/deployment/service.py",
    "docs/PROVIDERS.md",
    "docs/DEPLOYMENT.md",
}


def main() -> None:
    missing = sorted(path for path in REQUIRED_FILES if not (ROOT / path).exists())
    if missing:
        raise SystemExit(f"Patch 03 validation failed; missing files: {missing}")

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != "0.5.0-providers-deployment":
        raise SystemExit(f"Patch 03 validation failed; unexpected VERSION: {version}")

    settings = Settings()
    if settings.dry_run is not True:
        raise SystemExit("Patch 03 validation failed; DRY_RUN must default to true")
    if settings.allow_real_infrastructure_mutation is not False:
        raise SystemExit(
            "Patch 03 validation failed; real infrastructure mutation guard must default false"
        )

    # Import guard: dry-run adapter must be fully local and require no provider token/network.
    if DryRunProvider.__name__ != "DryRunProvider":
        raise SystemExit("Patch 03 validation failed; dry-run provider import failed")

    bot_files = sorted((ROOT / "app" / "bot").glob("*.py"))
    if [path.name for path in bot_files] != ["__init__.py"]:
        raise SystemExit("Patch 03 validation failed; Telegram Phase 7 was implemented too early")

    if (ROOT / "app" / "services" / "replacement.py").exists():
        raise SystemExit("Patch 03 validation failed; Phase 6 orchestrator was implemented too early")

    print("Patch 03 validation: PASS")


if __name__ == "__main__":
    main()
