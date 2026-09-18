from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    assert (ROOT / "VERSION").read_text().strip() in {
        "1.0.5-postgres-auth-hotfix",
        "1.0.6-operational-onboarding",
    }
    installer = (ROOT / "scripts" / "quick_install.sh").read_text()
    assert "reconcile_postgres_password" in installer
    assert "postgres_password_matches_env" in installer
    assert "ALTER ROLE %I WITH PASSWORD %L" in installer
    assert "\\getenv aso_target_password POSTGRES_PASSWORD" in installer
    assert "The database volume was NOT deleted." in installer
    for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "ASO_DATABASE_URL"):
        assert f"-u {key}" in installer
    start = installer.index("compose up -d postgres")
    reconcile = installer.index("reconcile_postgres_password", start)
    migration = installer.index("compose run --rm api alembic upgrade head")
    assert reconcile < migration
    print("Patch 10 PostgreSQL auth hotfix validation: PASS")


if __name__ == "__main__":
    main()
