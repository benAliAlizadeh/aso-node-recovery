from app.core.config import Settings


def test_dry_run_defaults_to_true() -> None:
    settings = Settings(_env_file=None)
    assert settings.dry_run is True


def test_secret_values_are_not_exposed_by_repr() -> None:
    settings = Settings(_env_file=None, telegram_bot_token="super-secret-token")
    representation = repr(settings.telegram_bot_token)
    assert "super-secret-token" not in representation


def test_monitoring_defaults_are_debounced_and_iran_scoped() -> None:
    settings = Settings(_env_file=None)
    assert settings.failure_threshold == 3
    assert settings.recovery_threshold == 2
    assert settings.check_host_country_code == "ir"
    assert settings.check_host_max_nodes == 5
    assert settings.check_host_min_success_nodes == 3


def test_check_host_quorum_cannot_exceed_selected_nodes() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, check_host_max_nodes=2, check_host_min_success_nodes=3)


def test_replacement_worker_and_emergency_controls_are_safe_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.replacement_worker_enabled is False
    assert settings.replacement_emergency_stop is False
    assert settings.replacement_job_lease_seconds >= settings.provisioning_timeout_seconds
