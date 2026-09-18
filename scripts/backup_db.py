from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backup import DatabaseBackupManager  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("ASO_DATABASE_URL is required")
    manager = DatabaseBackupManager(
        settings.database_url.get_secret_value(),
        settings.backup_dir,
        retention_count=settings.backup_retention_count,
        allow_restore=settings.allow_database_restore,
    )
    path = manager.create_backup()
    print(path)


if __name__ == "__main__":
    main()
