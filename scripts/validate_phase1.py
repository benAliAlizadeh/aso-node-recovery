from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_PATHS = (
    "PROJECT_SCOPE.md",
    "README.md",
    "VERSION",
    ".env.example",
    "docker-compose.yml",
    "pyproject.toml",
    "app/main.py",
    "app/core/config.py",
    "app/core/logging.py",
    "app/core/errors.py",
    "app/api/health.py",
    "tests/test_health.py",
)

FORBIDDEN_PHASE1_FILES = (
    "app/providers/hetzner.py",
    "app/providers/linode.py",
    "app/monitoring/check_host.py",
    "app/deployment/ssh.py",
    "app/database/session.py",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    missing = [path for path in REQUIRED_PATHS if not (root / path).exists()]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    premature = []
    if version.startswith("0.1."):
        premature = [path for path in FORBIDDEN_PHASE1_FILES if (root / path).exists()]

    scope = (root / "PROJECT_SCOPE.md").read_text(encoding="utf-8")
    required_scope_statements = (
        "does **not** maintain permanent spare VPS or IP pools",
        "old VPS **must never be deleted**",
        "`DRY_RUN` defaults to `true`",
    )
    missing_statements = [item for item in required_scope_statements if item not in scope]

    if missing or premature or missing_statements:
        if missing:
            print(f"Missing required paths: {missing}")
        if premature:
            print(f"Premature later-phase files: {premature}")
        if missing_statements:
            print(f"Missing scope invariants: {missing_statements}")
        return 1

    print("Phase 1 structural validation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
