from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quick_installer_hard_codes_safe_initial_switches() -> None:
    text = (ROOT / "scripts" / "quick_install.sh").read_text()
    assert "set_env ASO_DRY_RUN true" in text
    assert "set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION false" in text
    assert "set_env ASO_ALLOW_OLD_VPS_DELETION false" in text
    assert "set_env ASO_REPLACEMENT_WORKER_ENABLED false" in text
    assert "set_env ASO_WORKER_SCHEDULER_ENABLED false" in text
    assert "set_env ASO_ALLOW_DATABASE_RESTORE false" in text
    assert "set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION true" not in text
    assert "set_env ASO_ALLOW_OLD_VPS_DELETION true" not in text


def test_quick_installer_does_not_auto_remove_conflicting_packages() -> None:
    text = (ROOT / "scripts" / "quick_install.sh").read_text()
    assert "Conflicting container packages detected" in text
    assert "apt-get remove" not in text
    assert "apt-get purge" not in text


def test_asoctl_stop_never_removes_named_volumes() -> None:
    text = (ROOT / "scripts" / "asoctl.sh").read_text()
    assert "compose down" in text
    assert "down -v" not in text
    assert "down --volumes" not in text


def test_quick_install_release_version_is_consistent() -> None:
    assert (ROOT / "VERSION").read_text().strip() == "1.5.2-master-auto-routing"
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'version = "1.1.0"' in pyproject
    assert (ROOT / "docs" / "QUICK_INSTALL.md").is_file()
    assert (ROOT / "install.sh").is_file()
    assert (ROOT / "asoctl").is_file()


def test_production_compose_initializes_private_runtime_volumes() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    assert "runtime-init:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "chmod 0700 /var/lib/aso/secrets /var/lib/aso/backups" in compose
    assert "chown aso:aso /var/lib/aso/secrets /var/lib/aso/backups" in compose
    assert "- CHOWN" in compose
    assert "- FOWNER" in compose
    assert "- DAC_OVERRIDE" in compose
    assert 'network_mode: "none"' in compose


def test_quick_installer_runs_runtime_volume_initializer_before_migrations() -> None:
    text = (ROOT / "scripts" / "quick_install.sh").read_text()
    init_pos = text.index("compose run --rm --no-deps runtime-init")
    migration_pos = text.index("compose run --rm api alembic upgrade head")
    review_pos = text.index("compose run --rm api python scripts/security_review.py")
    assert init_pos < migration_pos < review_pos


def test_quick_installer_reconciles_existing_postgres_password_before_migrations() -> None:
    text = (ROOT / "scripts" / "quick_install.sh").read_text()
    start_pos = text.index('compose up -d postgres')
    wait_pos = text.index('wait_for_postgres', start_pos)
    reconcile_pos = text.index('reconcile_postgres_password', start_pos)
    migration_pos = text.index('compose run --rm api alembic upgrade head')
    assert start_pos < wait_pos < reconcile_pos < migration_pos
    assert 'ALTER ROLE %I WITH PASSWORD %L' in text
    assert '\\getenv aso_target_password POSTGRES_PASSWORD' in text
    assert 'postgres_password_matches_env' in text
    assert 'The database volume was NOT deleted.' in text


def test_compose_ignores_exported_database_variables() -> None:
    text = (ROOT / "scripts" / "quick_install.sh").read_text()
    compose_block = text[text.index('compose() {'):text.index('wait_for_postgres() {')]
    for key in ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'ASO_DATABASE_URL'):
        assert f'-u {key}' in compose_block
