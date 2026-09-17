from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import SafetyViolationError
from app.deployment.installer import ThreeXUiInstaller
from app.deployment.node_api import ThreeXUiNodeApiVerifier
from app.deployment.os_detection import RemoteBootstrapper, RemoteOsDetector
from app.deployment.ssh import SshReadinessProbe
from app.deployment.state import DeploymentStateMachine
from app.deployment.types import SshConnectionSpec, ThreeXUiConfig
from app.models.enums import DeploymentState
from app.models.operations import Deployment

TransitionCallback = Callable[[Deployment], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    config: ThreeXUiConfig
    dry_run: bool


class DeploymentService:
    """Crash-resumable deployment flow for one already-created replacement VPS.

    The persisted Deployment.state is a checkpoint. Re-entering the service resumes from that state
    rather than blindly restarting from PENDING. Each transition can be durably persisted by the
    orchestrator through ``on_transition``.
    """

    def __init__(
        self,
        settings: Settings,
        readiness: SshReadinessProbe,
        os_detector: RemoteOsDetector,
        bootstrapper: RemoteBootstrapper,
        installer: ThreeXUiInstaller,
        api_verifier: ThreeXUiNodeApiVerifier,
        state_machine: DeploymentStateMachine | None = None,
    ) -> None:
        self.settings = settings
        self.readiness = readiness
        self.os_detector = os_detector
        self.bootstrapper = bootstrapper
        self.installer = installer
        self.api_verifier = api_verifier
        self.state_machine = state_machine or DeploymentStateMachine()

    async def deploy(
        self,
        deployment: Deployment,
        ssh: SshConnectionSpec,
        *,
        public_host: str,
        on_transition: TransitionCallback | None = None,
    ) -> DeploymentResult:
        if deployment.state is None:
            deployment.state = DeploymentState.PENDING
        if self.settings.dry_run:
            await self._simulate_success(deployment, public_host, on_transition)
            return DeploymentResult(config=self._dry_run_config(public_host), dry_run=True)
        if not self.settings.allow_real_infrastructure_mutation:
            raise SafetyViolationError(
                "real SSH/deployment requires ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true"
            )

        installation_may_exist = deployment.state in {
            DeploymentState.INSTALLING,
            DeploymentState.VERIFYING,
            DeploymentState.SUCCEEDED,
        }
        try:
            if deployment.state is DeploymentState.PENDING:
                await self._transition(deployment, DeploymentState.WAITING_SSH, on_transition)

            if deployment.state is DeploymentState.WAITING_SSH:
                await self.readiness.wait(ssh)
                await self._transition(deployment, DeploymentState.BOOTSTRAPPING, on_transition)

            if deployment.state is DeploymentState.BOOTSTRAPPING:
                os_info = await self.os_detector.detect(ssh)
                await self.bootstrapper.bootstrap(ssh, os_info)
                await self._transition(deployment, DeploymentState.INSTALLING, on_transition)

            if deployment.state is DeploymentState.INSTALLING:
                installation_may_exist = True
                already_installed = False
                try:
                    await self.installer.verify_installation(ssh)
                    already_installed = True
                except Exception:
                    already_installed = False
                if not already_installed:
                    await self.installer.install(ssh, public_host=public_host)
                await self._transition(deployment, DeploymentState.VERIFYING, on_transition)

            if deployment.state in {DeploymentState.VERIFYING, DeploymentState.SUCCEEDED}:
                await self.installer.verify_installation(ssh)
                config = await self.installer.read_configuration(ssh)
                await self.api_verifier.verify(config)
                if deployment.state is DeploymentState.VERIFYING:
                    await self._transition(deployment, DeploymentState.SUCCEEDED, on_transition)
                return DeploymentResult(config=config, dry_run=False)

            raise RuntimeError(f"deployment cannot resume from state {deployment.state.value}")
        except Exception as exc:
            if deployment.state not in {DeploymentState.SUCCEEDED, DeploymentState.FAILED}:
                await self._transition(deployment, DeploymentState.FAILED, on_transition)
            deployment.error_code = exc.__class__.__name__[:64]
            deployment.error_message = str(exc)[:2000]
            if on_transition is not None:
                await on_transition(deployment)
            if installation_may_exist:
                try:
                    await self.installer.rollback(ssh)
                except Exception:
                    pass
            raise

    async def _transition(
        self,
        deployment: Deployment,
        target: DeploymentState,
        callback: TransitionCallback | None,
    ) -> None:
        self.state_machine.transition(deployment, target)
        if callback is not None:
            await callback(deployment)

    async def _simulate_success(
        self,
        deployment: Deployment,
        public_host: str,
        callback: TransitionCallback | None,
    ) -> None:
        del public_host
        remaining = {
            DeploymentState.PENDING: (
                DeploymentState.WAITING_SSH,
                DeploymentState.BOOTSTRAPPING,
                DeploymentState.INSTALLING,
                DeploymentState.VERIFYING,
                DeploymentState.SUCCEEDED,
            ),
            DeploymentState.WAITING_SSH: (
                DeploymentState.BOOTSTRAPPING,
                DeploymentState.INSTALLING,
                DeploymentState.VERIFYING,
                DeploymentState.SUCCEEDED,
            ),
            DeploymentState.BOOTSTRAPPING: (
                DeploymentState.INSTALLING,
                DeploymentState.VERIFYING,
                DeploymentState.SUCCEEDED,
            ),
            DeploymentState.INSTALLING: (
                DeploymentState.VERIFYING,
                DeploymentState.SUCCEEDED,
            ),
            DeploymentState.VERIFYING: (DeploymentState.SUCCEEDED,),
            DeploymentState.SUCCEEDED: (),
        }
        if deployment.state is DeploymentState.FAILED:
            raise RuntimeError("failed deployment requires a new attempt")
        for state in remaining[deployment.state]:
            await self._transition(deployment, state, callback)

    @staticmethod
    def _dry_run_config(public_host: str) -> ThreeXUiConfig:
        return ThreeXUiConfig(
            username="dry-run-admin",
            password=SecretStr("dry-run-panel-password"),
            panel_port=2053,
            web_base_path="dry-run-panel",
            access_url=f"http://{public_host}:2053/dry-run-panel",
            api_token=SecretStr("dry-run-node-api-token"),
            db_type="sqlite",
        )
