from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import SafetyViolationError
from app.deployment import (
    CommandResult,
    DeploymentService,
    DeploymentStateMachine,
    InvalidDeploymentTransitionError,
    RemoteBootstrapper,
    RemoteOsDetector,
    SshConnectionSpec,
    SshReadinessProbe,
    ThreeXUiConfig,
    ThreeXUiInstaller,
    ThreeXUiNodeApiVerifier,
)
from app.models import Deployment, DeploymentState, SshAuthMethod


class FakeExecutor:
    def __init__(self, results: list[CommandResult] | None = None) -> None:
        self.results = list(results or [])
        self.commands: list[str] = []

    async def run(
        self, spec: SshConnectionSpec, command: str, *, timeout_seconds: float | None = None
    ) -> CommandResult:
        self.commands.append(command)
        if self.results:
            return self.results.pop(0)
        return CommandResult(stdout="", stderr="", exit_status=0)


def ssh_spec() -> SshConnectionSpec:
    return SshConnectionSpec(
        host="203.0.113.20",
        port=22,
        username="root",
        auth_method=SshAuthMethod.PRIVATE_KEY,
        secret=SecretStr("/tmp/test-key"),
    )


def deployment() -> Deployment:
    return Deployment(
        replacement_job_id=uuid4(),
        vps_instance_id=uuid4(),
        attempt_number=1,
    )


def test_deployment_state_machine_rejects_skipping_steps() -> None:
    item = deployment()
    machine = DeploymentStateMachine()
    with pytest.raises(InvalidDeploymentTransitionError):
        machine.transition(item, DeploymentState.INSTALLING)


@pytest.mark.asyncio
async def test_os_detection_and_bootstrap_are_isolated_from_installer() -> None:
    executor = FakeExecutor(
        [
            CommandResult(
                stdout="ID=ubuntu\nVERSION_ID=24.04\nARCH=x86_64\n",
                stderr="",
                exit_status=0,
            ),
            CommandResult(stdout="", stderr="", exit_status=0),
        ]
    )
    info = await RemoteOsDetector(executor).detect(ssh_spec())
    await RemoteBootstrapper(executor).bootstrap(ssh_spec(), info)

    assert info.os_id == "ubuntu"
    assert "apt-get update" in executor.commands[1]
    assert all("3x-ui" not in command for command in executor.commands)


@pytest.mark.asyncio
async def test_installer_extracts_current_upstream_install_result_contract() -> None:
    raw = "\0".join(
        [
            "admin",
            "secret-pass",
            "2053",
            "panel-path",
            "http://203.0.113.20:2053/panel-path",
            "api-token",
            "sqlite",
            "",
        ]
    )
    executor = FakeExecutor([CommandResult(stdout=raw, stderr="", exit_status=0)])
    config = await ThreeXUiInstaller(executor).read_configuration(ssh_spec())

    assert config.username == "admin"
    assert config.password.get_secret_value() == "secret-pass"
    assert config.panel_port == 2053
    assert config.web_base_path == "panel-path"
    assert config.api_token.get_secret_value() == "api-token"
    assert "secret-pass" not in executor.commands[0]
    assert "api-token" not in executor.commands[0]


@pytest.mark.asyncio
async def test_node_api_verifier_uses_bearer_token_and_server_status_endpoint() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={"success": True, "obj": {"xray": {"state": "running"}, "cpu": 1}},
        )

    config = ThreeXUiConfig(
        username="admin",
        password=SecretStr("password"),
        panel_port=2053,
        web_base_path="panel",
        access_url="http://203.0.113.20:2053/panel",
        api_token=SecretStr("token-123"),
        db_type="sqlite",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ThreeXUiNodeApiVerifier(client=client).verify(config)

    assert captured["path"] == "/panel/panel/api/server/status"
    assert captured["authorization"] == "Bearer token-123"
    assert payload["xray"]["state"] == "running"


@pytest.mark.asyncio
async def test_deployment_dry_run_advances_state_without_ssh() -> None:
    executor = FakeExecutor()
    service = DeploymentService(
        Settings(dry_run=True),
        SshReadinessProbe(executor, timeout_seconds=0.1, poll_interval_seconds=0.01),
        RemoteOsDetector(executor),
        RemoteBootstrapper(executor),
        ThreeXUiInstaller(executor),
        ThreeXUiNodeApiVerifier(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))),
    )
    item = deployment()
    try:
        result = await service.deploy(item, ssh_spec(), public_host="203.0.113.20")
    finally:
        await service.api_verifier._client.aclose()  # type: ignore[union-attr]

    assert result.dry_run is True
    assert item.state is DeploymentState.SUCCEEDED
    assert executor.commands == []


@pytest.mark.asyncio
async def test_real_deployment_requires_second_explicit_safety_switch() -> None:
    executor = FakeExecutor()
    service = DeploymentService(
        Settings(dry_run=False, allow_real_infrastructure_mutation=False),
        SshReadinessProbe(executor, timeout_seconds=0.1, poll_interval_seconds=0.01),
        RemoteOsDetector(executor),
        RemoteBootstrapper(executor),
        ThreeXUiInstaller(executor),
        ThreeXUiNodeApiVerifier(),
    )
    with pytest.raises(SafetyViolationError):
        await service.deploy(deployment(), ssh_spec(), public_host="203.0.113.20")
    assert executor.commands == []
