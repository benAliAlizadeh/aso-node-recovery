from pathlib import Path

import pytest

from app.backup import DatabaseBackupManager
from app.core.errors import SafetyViolationError


def test_backup_uses_pg_dump_custom_format_without_password_in_argv(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run(command, *, check, env, capture_output, text):
        calls.append((command, env))
        if command[0] == "pg_dump":
            target = Path(command[command.index("--file") + 1])
            target.write_bytes(b"PGDMP")
        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = DatabaseBackupManager(
        "postgresql+asyncpg://aso:secret@db.example:5432/aso",
        str(tmp_path),
        retention_count=2,
    )
    backup = manager.create_backup()

    assert backup.exists()
    assert calls[0][0][:2] == ["pg_dump", "--format=custom"]
    assert all("secret" not in arg for command, _ in calls for arg in command)
    assert calls[0][1]["PGPASSWORD"] == "secret"
    assert any(command[:2] == ["pg_restore", "--list"] for command, _ in calls)


def test_restore_has_independent_guard(tmp_path) -> None:
    backup = tmp_path / "a.dump"
    backup.write_bytes(b"PGDMP")
    manager = DatabaseBackupManager(
        "postgresql+asyncpg://aso:secret@db.example:5432/aso",
        str(tmp_path),
        allow_restore=False,
    )
    with pytest.raises(SafetyViolationError):
        manager.restore(backup, confirmation=manager.RESTORE_CONFIRMATION)


def test_restore_test_refuses_production_database(tmp_path) -> None:
    backup = tmp_path / "a.dump"
    backup.write_bytes(b"PGDMP")
    manager = DatabaseBackupManager(
        "postgresql+asyncpg://aso:secret@db.example:5432/aso",
        str(tmp_path),
    )
    with pytest.raises(SafetyViolationError):
        manager.restore_test(backup, target_database="aso")
