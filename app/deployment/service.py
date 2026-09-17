from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    config: ThreeXUiConfig | None
    dry_run: bool


class DeploymentService:
    """Stateful deployment flow for one already-created replacement VPS."""

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
    ) -> DeploymentResult:
        if self.settings.dry_run:
            self._simulate_success(deployment)
            return DeploymentResult(config=None, dry_run=True)
        if not self.settings.allow_real_infrastructure_mutation:
            raise SafetyViolationError(
                "real SSH/deployment requires ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true"
            )

        installation_started = False
        try:
            self.state_machine.transition(deployment, DeploymentState.WAITING_SSH)
            await self.readiness.wait(ssh)

            self.state_machine.transition(deployment, DeploymentState.BOOTSTRAPPING)
            os_info = await self.os_detector.detect(ssh)
            await self.bootstrapper.bootstrap(ssh, os_info)

            self.state_machine.transition(deployment, DeploymentState.INSTALLING)
            installation_started = True
            await self.installer.install(ssh, public_host=public_host)

            self.state_machine.transition(deployment, DeploymentState.VERIFYING)
            await self.installer.verify_installation(ssh)
            config = await self.installer.read_configuration(ssh)
            await self.api_verifier.verify(config)

            self.state_machine.transition(deployment, DeploymentState.SUCCEEDED)
            return DeploymentResult(config=config, dry_run=False)
        except Exception as exc:
            if deployment.state not in {DeploymentState.SUCCEEDED, DeploymentState.FAILED}:
                self.state_machine.transition(deployment, DeploymentState.FAILED)
            deployment.error_code = exc.__class__.__name__[:64]
            deployment.error_message = str(exc)[:2000]
            if installation_started:
                try:
                    await self.installer.rollback(ssh)
                except Exception:
                    pass
            raise

    def _simulate_success(self, deployment: Deployment) -> None:
        for state in (
            DeploymentState.WAITING_SSH,
            DeploymentState.BOOTSTRAPPING,
            DeploymentState.INSTALLING,
            DeploymentState.VERIFYING,
            DeploymentState.SUCCEEDED,
        ):
            self.state_machine.transition(deployment, state)
