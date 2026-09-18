from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import inspect

from app.bot.callbacks import CallbackSigner
from app.core.config import Settings
from app.core.errors import SafetyViolationError
from app.models import Node, NodeOperationMode, Provider, ProviderType, RuntimeExecutionMode
from app.providers.dry_run import DryRunProvider
from app.providers.factory import ProviderFactory
from app.services.operational_settings import OperationalSettingsService

ROOT = Path(__file__).resolve().parents[1]


def test_node_operation_modes_are_explicit_and_persisted() -> None:
    assert {item.value for item in NodeOperationMode} == {
        "disabled",
        "monitor_only",
        "auto_repair",
    }
    table = inspect(Node).local_table
    assert "operation_mode" in table.c
    assert table.c.operation_mode.nullable is False


def test_live_capability_never_bypasses_host_safety() -> None:
    settings = Settings(_env_file=None)
    capable, reason = OperationalSettingsService.live_capability(settings)
    assert capable is False
    assert "DRY_RUN" in str(reason)

    settings = Settings(
        _env_file=None,
        dry_run=False,
        allow_real_infrastructure_mutation=True,
        replacement_emergency_stop=False,
    )
    capable, reason = OperationalSettingsService.live_capability(settings)
    assert capable is True
    assert reason is None


def test_provider_factory_runtime_dry_run_cannot_override_host_dry_run() -> None:
    provider = Provider(
        id=uuid4(),
        key="linode-main",
        display_name="Linode",
        provider_type=ProviderType.LINODE,
        credential_ref="unused-in-dry-run",
    )
    factory = ProviderFactory(Settings(_env_file=None, dry_run=True))
    adapter = factory.create(provider, dry_run=False)
    assert isinstance(adapter, DryRunProvider)


def test_real_provider_adapter_requires_hard_mutation_gate() -> None:
    provider = Provider(
        id=uuid4(),
        key="linode-main",
        display_name="Linode",
        provider_type=ProviderType.LINODE,
        credential_ref="unused",
    )
    factory = ProviderFactory(
        Settings(
            _env_file=None,
            dry_run=False,
            allow_real_infrastructure_mutation=False,
            replacement_emergency_stop=False,
        )
    )
    with pytest.raises(SafetyViolationError, match="ALLOW_REAL_INFRASTRUCTURE_MUTATION"):
        factory.create(provider, dry_run=False)


def test_runtime_callbacks_fit_telegram_limit() -> None:
    signer = CallbackSigner(SecretStr("s" * 32))
    for action in ("me", "md", "ae", "ad", "xl", "xd", "na", "nm", "nd"):
        payload = signer.encode(action, uuid4(), 100, now=6000)
        assert len(payload.encode("utf-8")) <= 64


def test_runtime_ui_has_separate_node_and_global_controls() -> None:
    source = (ROOT / "app" / "bot" / "runtime_ui.py").read_text(encoding="utf-8")
    for marker in (
        "Runtime Controls",
        "Monitoring",
        "Auto Repair Worker",
        "Request LIVE",
        "Monitor Only",
        "AUTO REPAIR",
        "Environment safety gates always override Telegram controls",
    ):
        assert marker in source


def test_auto_repair_worker_filters_nodes_and_dry_run_blocks_auto_trigger() -> None:
    source = (ROOT / "app" / "workers" / "replacement.py").read_text(encoding="utf-8")
    assert "list_auto_repair_failed" in source
    assert "effective_dry_run" in source
    assert "if effective_dry_run or self.settings.replacement_emergency_stop" in source


def test_orchestrator_persists_runtime_execution_mode_per_job() -> None:
    source = (ROOT / "app" / "replacement" / "orchestrator.py").read_text(encoding="utf-8")
    assert "effective_dry_run" in source
    assert "is_dry_run=effective_dry_run" in source
    assert "dry_run=job.is_dry_run" in source
    assert "get(provider, dry_run=job.is_dry_run)" in source


def test_runtime_execution_mode_enum_is_stable() -> None:
    assert RuntimeExecutionMode.DRY_RUN.value == "dry_run"
    assert RuntimeExecutionMode.LIVE.value == "live"
