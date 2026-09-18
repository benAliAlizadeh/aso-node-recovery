from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    checks: list[tuple[str, bool]] = [
        ("production environment", settings.environment == "production"),
        ("SSH host-key verification", settings.ssh_verify_host_key),
        ("node TLS verification", settings.three_xui_verify_tls),
        ("master TLS verification", settings.master_3xui_verify_tls),
        ("database restore disabled", not settings.allow_database_restore),
    ]
    if settings.telegram_bot_enabled:
        checks.extend(
            [
                (
                    "Telegram authorized users configured",
                    bool(settings.telegram_authorized_user_ids),
                ),
                (
                    "Telegram callback secret configured",
                    settings.telegram_callback_secret is not None,
                ),
            ]
        )

    secret_dir = Path(settings.runtime_secret_dir)
    if secret_dir.exists():
        mode = stat.S_IMODE(secret_dir.stat().st_mode)
        checks.append(("runtime secret directory is owner-only", mode & 0o077 == 0))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"[INFO] DRY_RUN={settings.dry_run}")
    print(
        "[INFO] ALLOW_REAL_INFRASTRUCTURE_MUTATION="
        f"{settings.allow_real_infrastructure_mutation}"
    )
    if failed:
        raise SystemExit("Security review failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
