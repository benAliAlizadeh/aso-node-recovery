from app.core.config import Settings


def test_dry_run_defaults_to_true() -> None:
    settings = Settings(_env_file=None)
    assert settings.dry_run is True


def test_secret_values_are_not_exposed_by_repr() -> None:
    settings = Settings(_env_file=None, telegram_bot_token="super-secret-token")
    representation = repr(settings.telegram_bot_token)
    assert "super-secret-token" not in representation
