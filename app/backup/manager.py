from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.errors import ConfigurationError, SafetyViolationError


class DatabaseBackupManager:
    """PostgreSQL custom-format backup/restore wrapper.

    Credentials are passed through libpq environment variables rather than command-line arguments.
    Restore is independently gated because it can overwrite database objects.
    """

    RESTORE_CONFIRMATION = "RESTORE_ASO_DATABASE"

    def __init__(
        self,
        database_url: str,
        backup_dir: str,
        *,
        retention_count: int = 14,
        allow_restore: bool = False,
    ) -> None:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise ConfigurationError("backup manager supports PostgreSQL only")
        if not url.database:
            raise ConfigurationError("PostgreSQL database name is required")
        self.url = url
        self.backup_dir = Path(backup_dir).expanduser().resolve()
        self.retention_count = retention_count
        self.allow_restore = allow_restore

    def create_backup(self) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.backup_dir, 0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = self.backup_dir / f"aso-{stamp}.dump"
        self._run(["pg_dump", "--format=custom", "--file", str(target)])
        if not target.exists():
            raise RuntimeError("pg_dump reported success but backup file is missing")
        os.chmod(target, 0o600)
        self.validate_backup(target)
        self._apply_retention()
        return target

    def validate_backup(self, path: str | Path) -> None:
        backup = self._validated_path(path)
        self._run(["pg_restore", "--list", str(backup)], include_database_env=False)

    def restore(self, path: str | Path, *, confirmation: str) -> None:
        if not self.allow_restore:
            raise SafetyViolationError("database restore is disabled by configuration")
        if confirmation != self.RESTORE_CONFIRMATION:
            raise SafetyViolationError("database restore confirmation phrase is invalid")
        backup = self._validated_path(path)
        self.validate_backup(backup)
        self._run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                self.url.database,
                str(backup),
            ]
        )

    def restore_test(self, path: str | Path, *, target_database: str) -> None:
        """Restore into a caller-provided isolated database; never cleans the production DB."""
        if not target_database.strip() or target_database == self.url.database:
            raise SafetyViolationError("restore test requires a separate target database")
        backup = self._validated_path(path)
        self.validate_backup(backup)
        env = self._connection_env(database=target_database)
        subprocess.run(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                target_database,
                str(backup),
            ],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )

    def _validated_path(self, path: str | Path) -> Path:
        backup = Path(path).expanduser().resolve()
        if not backup.is_file():
            raise FileNotFoundError(backup)
        return backup

    def _run(self, command: list[str], *, include_database_env: bool = True) -> None:
        env = self._connection_env() if include_database_env else os.environ.copy()
        subprocess.run(
            command,
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )

    def _connection_env(self, *, database: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        if self.url.host:
            env["PGHOST"] = self.url.host
        if self.url.port:
            env["PGPORT"] = str(self.url.port)
        if self.url.username:
            env["PGUSER"] = self.url.username
        if self.url.password:
            env["PGPASSWORD"] = self.url.password
        env["PGDATABASE"] = database or self.url.database
        return env

    def _apply_retention(self) -> None:
        backups = sorted(
            self.backup_dir.glob("aso-*.dump"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old in backups[self.retention_count :]:
            old.unlink()
