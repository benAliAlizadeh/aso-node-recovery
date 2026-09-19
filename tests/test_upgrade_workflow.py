from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_command_is_in_place_and_preserves_state() -> None:
    source = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    block = source[source.index("upgrade_stack() {"):source.index("setup_registry() {")]

    for required in (
        'compose --profile ops run --rm backup',
        'compose build',
        'compose run --rm api alembic upgrade head',
        'compose up -d --force-recreate api worker',
        'validate_release',
        'core.fileMode false',
    ):
        assert required in block

    for forbidden in (
        'down -v',
        'down --volumes',
        'docker volume prune',
        'docker volume rm',
        'rm .env',
        'quick_install.sh',
    ):
        assert forbidden not in block


def test_validate_uses_latest_available_release_validator() -> None:
    source = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    assert "latest_validator()" in source
    assert "sort -V | tail -n 1" in source
    assert 'python "/source/scripts/${validator}"' in source
    assert "validate_patch19.py" not in source


def test_upgrade_is_documented_as_git_pull_then_upgrade() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "UPGRADE.md").read_text(encoding="utf-8")
    assert "git config core.fileMode false" in readme
    assert "git pull --ff-only" in readme
    assert "./asoctl upgrade" in readme
    assert "PostgreSQL volume" in doc
    assert "runtime secret volume" in doc


def test_fresh_installer_normalizes_git_filemode_noise() -> None:
    installer = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
    assert 'git -C "$PROJECT_ROOT" config core.fileMode false' in installer
