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
    assert settings.replacement_emergency_stop is True
    assert settings.replacement_job_lease_seconds >= settings.provisioning_timeout_seconds
    assert settings.replacement_vps_boot_grace_seconds == 180



def test_telegram_is_disabled_and_restore_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.telegram_bot_enabled is False
    assert settings.telegram_authorized_user_ids == ()
    assert settings.allow_database_restore is False
    assert settings.worker_scheduler_enabled is False


def test_enabled_telegram_requires_allowlist_and_callback_secret() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            telegram_bot_enabled=True,
            telegram_bot_token="token",
        )

    settings = Settings(
        _env_file=None,
        telegram_bot_enabled=True,
        telegram_bot_token="token",
        telegram_authorized_user_ids=(123,),
        telegram_callback_secret="x" * 32,
    )
    assert settings.telegram_authorized_user_ids == (123,)


def test_production_allows_disabled_ssh_host_key_but_requires_tls_verification() -> None:
    import pytest
    from pydantic import ValidationError

    settings = Settings(_env_file=None, environment="production", ssh_verify_host_key=False)
    assert settings.ssh_verify_host_key is False
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", master_3xui_verify_tls=False)


def test_old_vps_delete_requires_three_independent_real_mutation_gates() -> None:
    import pytest
    with pytest.raises(ValueError, match="old VPS deletion cannot be enabled"):
        Settings(allow_old_vps_deletion=True)
    with pytest.raises(ValueError, match="ALLOW_REAL_INFRASTRUCTURE_MUTATION"):
        Settings(dry_run=False, allow_old_vps_deletion=True, old_vps_delete_confirmation="DELETE_ONLY_VERIFIED_OLD_VPS")
    with pytest.raises(ValueError, match="exact confirmation phrase"):
        Settings(dry_run=False, allow_real_infrastructure_mutation=True, allow_old_vps_deletion=True)
    settings = Settings(
        dry_run=False,
        allow_real_infrastructure_mutation=True,
        allow_old_vps_deletion=True,
        old_vps_delete_confirmation="DELETE_ONLY_VERIFIED_OLD_VPS",
    )
    assert settings.allow_old_vps_deletion is True
