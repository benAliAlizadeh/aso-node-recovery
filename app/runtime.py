from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from app.control import ControlService
from app.core.config import Settings
from app.database import Database
from app.deployment.credentials import NodeSshSpecFactory
from app.deployment.installer import ThreeXUiInstaller
from app.deployment.node_api import ThreeXUiNodeApiVerifier
from app.deployment.os_detection import RemoteBootstrapper, RemoteOsDetector
from app.deployment.service import DeploymentService
from app.deployment.ssh import AsyncSshCommandExecutor, SshReadinessProbe
from app.master.client import Master3XUiClient
from app.master.factory import Master3XUiClientFactory
from app.monitoring.check_host import CheckHostClient
from app.providers.factory import ProviderFactory
from app.providers.manager import ProviderManager
from app.providers.policy import ProvisioningSafetyPolicy
from app.providers.provisioning import ProvisioningService
from app.replacement.orchestrator import ReplacementOrchestrator
from app.replacement.reachability import ReplacementReachabilityVerifier
from app.services.operational_settings import OperationalSettingsService
from app.workers.monitoring import MonitoringWorker
from app.workers.replacement import ReplacementWorker


@dataclass(slots=True)
class RuntimeContainer:
    """Composition root for worker and Telegram processes."""

    settings: Settings
    database: Database
    check_host: CheckHostClient
    provider_manager: ProviderManager
    master: Master3XUiClient
    operational_settings: OperationalSettingsService
    monitoring_worker: MonitoringWorker
    replacement_worker: ReplacementWorker
    orchestrator: ReplacementOrchestrator
    control: ControlService

    @classmethod
    def build(cls, settings: Settings) -> "RuntimeContainer":
        database = Database.from_settings(settings)
        operational_settings = OperationalSettingsService(database)

        check_host = CheckHostClient(
            base_url=settings.check_host_base_url,
            timeout_seconds=settings.check_host_result_timeout_seconds,
        )
        monitoring = MonitoringWorker(
            database,
            check_host,
            settings,
            operational_settings=operational_settings,
        )

        provider_manager = ProviderManager(ProviderFactory(settings))
        safety = ProvisioningSafetyPolicy(
            max_replacement_attempts=settings.max_replacement_attempts,
            max_temporary_servers=settings.max_temporary_servers,
            max_concurrent_replacements=settings.max_concurrent_replacements,
        )
        provisioning = ProvisioningService(
            safety,
            timeout_seconds=settings.provisioning_timeout_seconds,
            poll_interval_seconds=settings.provisioning_poll_interval_seconds,
        )

        executor = AsyncSshCommandExecutor()
        deployment = DeploymentService(
            settings,
            SshReadinessProbe(
                executor,
                timeout_seconds=settings.ssh_ready_timeout_seconds,
                poll_interval_seconds=settings.ssh_poll_interval_seconds,
            ),
            RemoteOsDetector(executor),
            RemoteBootstrapper(executor),
            ThreeXUiInstaller(executor, version=settings.three_xui_version),
            ThreeXUiNodeApiVerifier(
                verify_tls=settings.three_xui_verify_tls,
                timeout_seconds=settings.master_3xui_timeout_seconds,
            ),
        )

        if settings.master_3xui_base_url:
            master = Master3XUiClientFactory.create(settings)
        elif settings.dry_run:
            # Dry-run checkpoints do not perform a Master mutation. A non-routable placeholder keeps
            # the composition root usable for safe simulations without requiring production secrets.
            master = Master3XUiClient(
                "https://dry-run.invalid",
                api_token=SecretStr("dry-run-placeholder"),
            )
        else:
            raise ValueError("Master 3X-UI configuration is required outside DRY_RUN")

        orchestrator = ReplacementOrchestrator(
            database=database,
            settings=settings,
            provider_manager=provider_manager,
            provisioning=provisioning,
            deployment=deployment,
            ssh_factory=NodeSshSpecFactory(settings),
            reachability=ReplacementReachabilityVerifier(check_host, settings),
            master=master,
            operational_settings=operational_settings,
        )
        replacement_worker = ReplacementWorker(
            database,
            orchestrator,
            settings,
            operational_settings=operational_settings,
        )
        control = ControlService(
            database,
            settings,
            monitoring,
            orchestrator,
            operational_settings,
        )
        return cls(
            settings=settings,
            database=database,
            check_host=check_host,
            provider_manager=provider_manager,
            master=master,
            operational_settings=operational_settings,
            monitoring_worker=monitoring,
            replacement_worker=replacement_worker,
            orchestrator=orchestrator,
            control=control,
        )

    async def close(self) -> None:
        await self.check_host.aclose()
        await self.provider_manager.close()
        await self.master.aclose()
        await self.database.dispose()
