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
        secret_stat = secret_dir.stat()
        mode = stat.S_IMODE(secret_stat.st_mode)
        checks.append(("runtime secret directory is owner-only", mode & 0o077 == 0))
        checks.append(
            (
                "runtime secret directory is owned by the runtime user",
                secret_stat.st_uid == os.geteuid(),
            )
        )

    known_hosts = Path(settings.effective_ssh_known_hosts_path)
    if known_hosts.exists():
        known_hosts_stat = known_hosts.stat()
        known_hosts_mode = stat.S_IMODE(known_hosts_stat.st_mode)
        checks.append(("SSH known_hosts is owner-only", known_hosts_mode & 0o077 == 0))
        checks.append(
            (
                "SSH known_hosts is owned by the runtime user",
                known_hosts_stat.st_uid == os.geteuid(),
            )
        )

    backup_dir = Path(settings.backup_dir)
    if backup_dir.exists():
        backup_stat = backup_dir.stat()
        backup_mode = stat.S_IMODE(backup_stat.st_mode)
        checks.append(("runtime backup directory is owner-only", backup_mode & 0o077 == 0))
        checks.append(
            (
                "runtime backup directory is owned by the runtime user",
                backup_stat.st_uid == os.geteuid(),
            )
        )

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"[INFO] DRY_RUN={settings.dry_run}")
    print(
        "[INFO] ALLOW_REAL_INFRASTRUCTURE_MUTATION="
        f"{settings.allow_real_infrastructure_mutation}"
    )
    print(f"[INFO] ALLOW_OLD_VPS_DELETION={settings.allow_old_vps_deletion}")
    print(f"[INFO] REPLACEMENT_EMERGENCY_STOP={settings.replacement_emergency_stop}")
    if failed:
        raise SystemExit("Security review failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
