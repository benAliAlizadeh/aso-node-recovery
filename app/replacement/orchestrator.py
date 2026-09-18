from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import ConfigurationError, SafetyViolationError
from app.core.secrets import RuntimeSecretStore, SecretResolver
from app.database import Database
from app.database.repositories import (
    DeploymentRepository,
    EventRepository,
    NodeCredentialRepository,
    NodeRepository,
    ProviderRepository,
    ReplacementJobRepository,
    VpsInstanceRepository,
)
from app.deployment.credentials import NodeSshSpecFactory
from app.deployment.service import DeploymentService
from app.master import Master3XUiClient, MasterNodeMutation
from app.master.errors import MasterNodeVerificationError, MasterTransientError
from app.models import (
    Deployment,
    DeploymentState,
    Event,
    EventSeverity,
    EventType,
    Node,
    NodeCredential,
    NodeState,
    Provider,
    ProviderType,
    ReplacementCheckpoint,
    ReplacementJob,
    ReplacementJobState,
    SecretReferenceBackend,
    SshAuthMethod,
    VpsInstance,
    VpsInstanceRole,
    VpsInstanceState,
)
from app.monitoring.types import ReachabilityDecision
from app.providers.errors import ProviderNotFoundError, ProviderTransientError
from app.providers.manager import ProviderManager
from app.providers.provisioning import ProvisioningService
from app.providers.types import (
    CreateServerRequest,
    ProviderServer,
    ProviderServerStatus,
    ProvisioningCapacity,
)
from app.replacement.errors import (
    ReplacementBusyError,
    ReplacementConfigurationError,
    ReplacementDeferredError,
)
from app.replacement.locks import PostgresGlobalReplacementLock
from app.replacement.reachability import ReplacementReachabilityVerifier
from app.replacement.safety import OldVpsProtectionGuard
from app.replacement.state import ReplacementStateMachine
from app.services.node_state import NodeStateMachine
from app.services.operational_settings import OperationalSettingsService

logger = logging.getLogger(__name__)

_TERMINAL = frozenset(
    {
        ReplacementCheckpoint.COMPLETED,
        ReplacementCheckpoint.FAILED,
        ReplacementCheckpoint.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class ReplacementRunResult:
    job_id: UUID
    checkpoint: ReplacementCheckpoint
    terminal: bool
    deferred: bool = False
    reason: str | None = None


class ReplacementOrchestrator:
    """Durable, idempotent node-replacement workflow.

    Every external mutation is bracketed by persisted checkpoints. The old VPS deletion path is
    isolated behind ``OldVpsProtectionGuard`` and is never reached until deployment, master switch,
    master verification, and the final Iran reachability check have durable success markers.
    """

    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        provider_manager: ProviderManager,
        provisioning: ProvisioningService,
        deployment: DeploymentService,
        ssh_factory: NodeSshSpecFactory,
        reachability: ReplacementReachabilityVerifier,
        master: Master3XUiClient,
        secret_resolver: SecretResolver | None = None,
        runtime_secret_store: RuntimeSecretStore | None = None,
        admission_lock: PostgresGlobalReplacementLock | None = None,
        state_machine: ReplacementStateMachine | None = None,
        old_vps_guard: OldVpsProtectionGuard | None = None,
        operational_settings: OperationalSettingsService | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.provider_manager = provider_manager
        self.provisioning = provisioning
        self.deployment = deployment
        self.ssh_factory = ssh_factory
        self.reachability = reachability
        self.master = master
        self.secret_resolver = secret_resolver or SecretResolver()
        self.runtime_secret_store = runtime_secret_store or RuntimeSecretStore(
            settings.runtime_secret_dir
        )
        self.admission_lock = admission_lock or PostgresGlobalReplacementLock(database)
        self.state_machine = state_machine or ReplacementStateMachine()
        self.old_vps_guard = old_vps_guard or OldVpsProtectionGuard()
        self.operational_settings = operational_settings

    async def _assert_not_paused(self) -> None:
        if self.operational_settings is not None and await self.operational_settings.is_paused():
            raise ReplacementDeferredError("system is paused")

    async def trigger(self, node_id: UUID) -> UUID:
        """Create one active replacement job for a FAILED node, idempotently."""
        effective_dry_run = (
            await self.operational_settings.effective_dry_run(self.settings)
            if self.operational_settings is not None
            else self.settings.dry_run
        )
        self._assert_not_emergency_stopped(dry_run=effective_dry_run)
        await self._assert_not_paused()
        async with self.admission_lock.acquire() as acquired:
            if not acquired:
                raise ReplacementBusyError("replacement admission lock is busy")

            async with self.database.session() as session:
                nodes = NodeRepository(session)
                jobs = ReplacementJobRepository(session)
                vps = VpsInstanceRepository(session)

                node = await nodes.get(node_id)
                if node is None:
                    raise ReplacementConfigurationError("node does not exist")
                active = await jobs.get_active_for_node(node_id)
                if active is not None:
                    return active.id
                if node.state is not NodeState.FAILED:
                    raise ReplacementConfigurationError(
                        f"replacement requires FAILED node; current state={node.state.value}"
                    )
                if await jobs.count_active() >= self.settings.max_concurrent_replacements:
                    raise ReplacementBusyError("maximum concurrent replacements reached")

                old_vps = await vps.get_current_for_node(node_id)
                if old_vps is None:
                    raise ReplacementConfigurationError(
                        "node has no registered current VPS; refusing replacement"
                    )
                provider = await ProviderRepository(session).get(node.provider_id)
                if provider is None or not provider.is_active:
                    raise ReplacementConfigurationError("node provider is missing or inactive")

                job = ReplacementJob(
                    node_id=node.id,
                    state=ReplacementJobState.PENDING,
                    checkpoint=ReplacementCheckpoint.CREATED,
                    active_slot=True,
                    is_dry_run=effective_dry_run,
                    attempt_count=0,
                    max_attempts=self.settings.max_replacement_attempts,
                    old_vps_instance_id=old_vps.id,
                )
                await jobs.add(job)
                if not job.is_dry_run:
                    NodeStateMachine.transition(node, NodeState.REPLACING)
                await self._add_event(
                    session,
                    job,
                    EventType.REPLACEMENT_STARTED,
                    "Replacement workflow started",
                    payload={"dry_run": job.is_dry_run},
                )
                await session.commit()
                return job.id

    async def resume(self, job_id: UUID) -> ReplacementRunResult:
        """Resume an active job from its durable checkpoint.

        A per-job database lease prevents two workers from executing the same workflow. Transient or
        indeterminate external state returns a deferred result without consuming a replacement
        attempt or marking the job failed.
        """
        await self._assert_not_paused()
        token = uuid4().hex
        if not await self._acquire_lease(job_id, token):
            raise ReplacementBusyError("replacement job is already leased by another worker")

        try:
            for _ in range(64):
                checkpoint = await self._get_checkpoint(job_id)
                if checkpoint in _TERMINAL:
                    return ReplacementRunResult(job_id, checkpoint, terminal=True)
                try:
                    job_dry_run = await self._job_is_dry_run(job_id)
                    await self._assert_runtime_execution_allowed(job_dry_run)
                    self._assert_not_emergency_stopped(dry_run=job_dry_run)
                    await self._assert_not_paused()
                    await self._dispatch(job_id, token, checkpoint)
                except (
                    ReplacementDeferredError,
                    ProviderTransientError,
                    MasterTransientError,
                ) as exc:
                    logger.info(
                        "replacement_deferred",
                        extra={"job_id": str(job_id), "checkpoint": checkpoint.value},
                    )
                    return ReplacementRunResult(
                        job_id,
                        await self._get_checkpoint(job_id),
                        terminal=False,
                        deferred=True,
                        reason=str(exc),
                    )
                except Exception as exc:
                    logger.exception(
                        "replacement_failed",
                        extra={"job_id": str(job_id), "checkpoint": checkpoint.value},
                    )
                    await self._fail_job(job_id, exc)
                    return ReplacementRunResult(
                        job_id,
                        ReplacementCheckpoint.FAILED,
                        terminal=True,
                        reason=str(exc),
                    )
            raise RuntimeError("replacement workflow exceeded internal checkpoint step limit")
        finally:
            await self._release_lease(job_id, token)

    async def cancel(self, job_id: UUID) -> None:
        """Cancel only before a master switch has been recorded."""
        async with self.database.session() as session:
            job = await ReplacementJobRepository(session).get(job_id)
            if job is None:
                raise ReplacementConfigurationError("replacement job does not exist")
            if job.checkpoint in _TERMINAL:
                return
            if job.master_updated_at is not None:
                raise SafetyViolationError(
                    "cannot cancel after master update; resume verification/rollback instead"
                )
            self.state_machine.transition(job, ReplacementCheckpoint.CANCELLED)
            node = await NodeRepository(session).get(job.node_id)
            if node is not None and not job.is_dry_run and node.state in {
                NodeState.REPLACING,
                NodeState.DEPLOYING,
                NodeState.VERIFYING,
            }:
                NodeStateMachine.transition(node, NodeState.FAILED)
            await session.commit()

    async def _dispatch(
        self, job_id: UUID, lease_token: str, checkpoint: ReplacementCheckpoint
    ) -> None:
        handlers = {
            ReplacementCheckpoint.CREATED: self._stage_created,
            ReplacementCheckpoint.PROVISIONING: self._stage_provisioning,
            ReplacementCheckpoint.PROVISIONED: self._stage_provisioned,
            ReplacementCheckpoint.CHECKING_IP: self._stage_checking_ip,
            ReplacementCheckpoint.TEMP_CLEANUP: self._stage_temp_cleanup,
            ReplacementCheckpoint.IP_VERIFIED: self._stage_ip_verified,
            ReplacementCheckpoint.DEPLOYING: self._stage_deploying,
            ReplacementCheckpoint.NODE_VERIFIED: self._stage_node_verified,
            ReplacementCheckpoint.MASTER_UPDATING: self._stage_master_updating,
            ReplacementCheckpoint.MASTER_UPDATED: self._stage_master_updated,
            ReplacementCheckpoint.MASTER_VERIFYING: self._stage_master_verifying,
            ReplacementCheckpoint.MASTER_VERIFIED: self._stage_master_verified,
            ReplacementCheckpoint.FINAL_CHECK: self._stage_final_check,
            ReplacementCheckpoint.FINAL_VERIFIED: self._stage_final_verified,
            ReplacementCheckpoint.OLD_VPS_CLEANUP: self._stage_old_vps_cleanup,
        }
        handler = handlers.get(checkpoint)
        if handler is None:
            raise RuntimeError(f"no replacement handler for {checkpoint.value}")
        await handler(job_id, lease_token)

    async def _stage_created(self, job_id: UUID, lease_token: str) -> None:
        del lease_token
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if job.attempt_count < 1:
                job.attempt_count = 1
            self.state_machine.transition(job, ReplacementCheckpoint.PROVISIONING)
            await session.commit()

    async def _stage_provisioning(self, job_id: UUID, lease_token: str) -> None:
        now = datetime.now(UTC)
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            node = await self._require_node(session, job.node_id)
            provider = await self._require_provider(session, node.provider_id)
            credential = await self._require_credential(session, node.id)
            vps_repo = VpsInstanceRepository(session)
            if job.new_vps_instance_id is not None:
                existing_vps = await vps_repo.get(job.new_vps_instance_id)
                if existing_vps is not None and existing_vps.state is not VpsInstanceState.DELETED:
                    self.state_machine.transition(job, ReplacementCheckpoint.PROVISIONED)
                    await session.commit()
                    return
            active_temporary = await vps_repo.count_active_replacements()
            active_jobs = await ReplacementJobRepository(session).count_active()
            old_vps = (
                await vps_repo.get(job.old_vps_instance_id)
                if job.old_vps_instance_id is not None
                else None
            )
            if old_vps is None:
                raise ReplacementConfigurationError("replacement job old VPS template is missing")
            request = self._build_create_request(job, node, provider, credential, old_vps)
            requested_at = job.provisioning_requested_at
            await session.commit()

        adapter = self.provider_manager.get(provider, dry_run=job.is_dry_run)
        provider_server = await adapter.find_server_by_name(request.name)
        if provider_server is None:
            if requested_at is not None:
                requested_at = self._as_utc(requested_at)
                age = (now - requested_at).total_seconds()
                if age < self.settings.provider_reconcile_grace_seconds:
                    raise ReplacementDeferredError(
                        "provider create reconciliation grace period is still active"
                    )

            capacity = ProvisioningCapacity(
                active_temporary_servers=active_temporary,
                active_replacements=max(0, active_jobs - 1),
            )
            async with self.database.session() as session:
                job = await self._require_job(session, job_id)
                job.provisioning_requested_at = datetime.now(UTC)
                await self._renew_lease_in_session(session, job_id, lease_token)
                await session.commit()
            try:
                provider_server = await self.provisioning.create_temporary(
                    adapter,
                    request,
                    attempt_number=job.attempt_count,
                    capacity=capacity,
                )
            except ProviderTransientError as exc:
                # The POST outcome may be ambiguous. Never blind-retry here; the next
                # resume searches provider state first.
                # the deterministic name first, then observes the reconciliation grace period.
                raise ReplacementDeferredError(str(exc)) from exc

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            vps_repo = VpsInstanceRepository(session)
            instance = await vps_repo.get_by_provider_identity(
                provider.id, provider_server.provider_server_id
            )
            created_record = instance is None
            if instance is None:
                instance = VpsInstance(
                    provider_id=provider.id,
                    node_id=job.node_id,
                    provider_server_id=provider_server.provider_server_id,
                    role=VpsInstanceRole.REPLACEMENT,
                    state=self._map_vps_state(provider_server.status),
                    host=provider_server.ipv4,
                    region=provider_server.region,
                    server_type=provider_server.server_type or request.server_type,
                    image=provider_server.image or request.image,
                )
                await vps_repo.add(instance)
            else:
                instance.state = self._map_vps_state(provider_server.status)
                instance.host = provider_server.ipv4 or instance.host
                instance.region = provider_server.region or instance.region
                instance.server_type = provider_server.server_type or instance.server_type
                instance.image = provider_server.image or instance.image or request.image
            job.new_vps_instance_id = instance.id
            self.state_machine.transition(job, ReplacementCheckpoint.PROVISIONED)
            if created_record:
                await self._add_event(
                    session,
                    job,
                    EventType.VPS_CREATED,
                    "Replacement VPS created/reconciled",
                    payload={"attempt": job.attempt_count, "provider": provider.key},
                )
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

    async def _stage_provisioned(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            new_vps = await self._require_new_vps(session, job)
            provider = await self._require_provider(session, new_vps.provider_id)
            provider_server_id = new_vps.provider_server_id
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        adapter = self.provider_manager.get(provider, dry_run=job.is_dry_run)
        try:
            server = await self.provisioning.wait_until_ready(adapter, provider_server_id)
        except ProviderNotFoundError:
            async with self.database.session() as session:
                job = await self._require_job(session, job_id)
                new_vps = await self._require_new_vps(session, job)
                new_vps.state = VpsInstanceState.DELETED
                self.state_machine.transition(job, ReplacementCheckpoint.TEMP_CLEANUP)
                await session.commit()
            return

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            new_vps = await self._require_new_vps(session, job)
            new_vps.host = server.ipv4
            new_vps.state = VpsInstanceState.RUNNING
            new_vps.region = server.region or new_vps.region
            new_vps.server_type = server.server_type or new_vps.server_type
            new_vps.image = server.image or new_vps.image
            self.state_machine.transition(job, ReplacementCheckpoint.CHECKING_IP)
            await self._add_event(
                session,
                job,
                EventType.IP_CHECK_STARTED,
                "Replacement IP reachability check started",
            )
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

    async def _stage_checking_ip(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            new_vps = await self._require_new_vps(session, job)
            host = self._require_host(new_vps)
            is_dry_run = job.is_dry_run
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        if is_dry_run:
            decision = ReachabilityDecision.REACHABLE
            summary_payload: dict[str, Any] = {"dry_run": True}
        else:
            result = await self.reachability.verify(host)
            decision = result.decision
            summary_payload = {
                "success_count": result.summary.success_count,
                "failure_count": result.summary.failure_count,
                "total_nodes": result.summary.total_nodes,
            }

        if decision is ReachabilityDecision.INDETERMINATE:
            raise ReplacementDeferredError("replacement IP reachability is indeterminate")

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if decision is ReachabilityDecision.UNREACHABLE:
                await self._add_event(
                    session,
                    job,
                    EventType.IP_CHECK_FAILED,
                    "Replacement IP failed Iran reachability quorum",
                    severity=EventSeverity.WARNING,
                    payload=summary_payload,
                )
                self.state_machine.transition(job, ReplacementCheckpoint.TEMP_CLEANUP)
            else:
                job.new_ip_verified_at = datetime.now(UTC)
                await self._add_event(
                    session,
                    job,
                    EventType.IP_CHECK_PASSED,
                    "Replacement IP passed Iran reachability quorum",
                    payload=summary_payload,
                )
                self.state_machine.transition(job, ReplacementCheckpoint.IP_VERIFIED)
            await session.commit()

    async def _stage_temp_cleanup(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            new_vps = (
                await VpsInstanceRepository(session).get(job.new_vps_instance_id)
                if job.new_vps_instance_id is not None
                else None
            )
            provider = (
                await self._require_provider(session, new_vps.provider_id)
                if new_vps is not None
                else None
            )
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        if (
            new_vps is not None
            and provider is not None
            and new_vps.state is not VpsInstanceState.DELETED
        ):
            adapter = self.provider_manager.get(provider, dry_run=job.is_dry_run)
            async with self.database.session() as session:
                job = await self._require_job(session, job_id)
                node = await self._require_node(session, job.node_id)
                expected_name = self._replacement_server_name(node, job)
            try:
                provider_temp = await adapter.get_server(new_vps.provider_server_id)
            except ProviderNotFoundError:
                provider_temp = None
            if provider_temp is not None:
                if provider_temp.provider_server_id != new_vps.provider_server_id:
                    raise SafetyViolationError(
                        "temporary VPS cleanup denied; provider identity mismatch"
                    )
                if provider_temp.name != expected_name:
                    raise SafetyViolationError(
                        "temporary VPS cleanup denied; provider server name does not match "
                        "the deterministic replacement identity"
                    )
                if new_vps.host and provider_temp.ipv4 != new_vps.host:
                    raise SafetyViolationError(
                        "temporary VPS cleanup denied; provider IP does not match registry identity"
                    )
                await self.provisioning.delete_temporary(adapter, new_vps.provider_server_id)

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if job.new_vps_instance_id is not None:
                instance = await VpsInstanceRepository(session).get(job.new_vps_instance_id)
                if instance is not None:
                    instance.state = VpsInstanceState.DELETED
            job.new_vps_instance_id = None
            job.provisioning_requested_at = None
            exhausted = job.attempt_count >= job.max_attempts
            if not exhausted:
                job.attempt_count += 1
                self.state_machine.transition(job, ReplacementCheckpoint.PROVISIONING)
            await session.commit()
        if exhausted:
            raise SafetyViolationError("replacement attempt limit reached after bad IP cleanup")

    async def _stage_ip_verified(self, job_id: UUID, lease_token: str) -> None:
        del lease_token
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            new_vps = await self._require_new_vps(session, job)
            deployments = DeploymentRepository(session)
            deployment = await deployments.get_for_attempt(job.id, job.attempt_count)
            created = deployment is None
            if deployment is None:
                deployment = Deployment(
                    replacement_job_id=job.id,
                    vps_instance_id=new_vps.id,
                    attempt_number=job.attempt_count,
                    state=DeploymentState.PENDING,
                )
                await deployments.add(deployment)
            node = await self._require_node(session, job.node_id)
            if not job.is_dry_run and node.state is NodeState.REPLACING:
                NodeStateMachine.transition(node, NodeState.DEPLOYING)
            if created:
                await self._add_event(
                    session,
                    job,
                    EventType.DEPLOYMENT_STARTED,
                    "3X-UI deployment started",
                    payload={"attempt": job.attempt_count},
                )
            self.state_machine.transition(job, ReplacementCheckpoint.DEPLOYING)
            await session.commit()

    async def _stage_deploying(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            node = await self._require_node(session, job.node_id)
            credential = await self._require_credential(session, node.id)
            new_vps = await self._require_new_vps(session, job)
            deployment = await self._require_deployment(session, job)
            host = self._require_host(new_vps)
            ssh = self.ssh_factory.create(credential, host=host)
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

            async def persist_transition(current: Deployment) -> None:
                del current
                await self._renew_lease_in_session(session, job_id, lease_token)
                await session.commit()

            try:
                result = await self.deployment.deploy(
                    deployment,
                    ssh,
                    public_host=host,
                    on_transition=persist_transition,
                    dry_run=job.is_dry_run,
                )
            except Exception:
                await self._add_event(
                    session,
                    job,
                    EventType.DEPLOYMENT_FAILED,
                    "3X-UI deployment failed",
                    severity=EventSeverity.ERROR,
                    payload={"attempt": job.attempt_count},
                )
                await session.commit()
                raise

            scope = f"replacement-{job.id.hex}-a{job.attempt_count}"
            deployment.api_token_ref = self.runtime_secret_store.write(
                scope, "node-api-token", result.config.api_token
            )
            deployment.panel_password_ref = self.runtime_secret_store.write(
                scope, "panel-password", result.config.password
            )
            deployment.panel_username = result.config.username
            deployment.panel_port = result.config.panel_port
            deployment.web_base_path = result.config.web_base_path
            deployment.access_url = result.config.access_url
            deployment.db_type = result.config.db_type
            job.deployment_verified_at = datetime.now(UTC)
            if not job.is_dry_run and node.state is NodeState.DEPLOYING:
                NodeStateMachine.transition(node, NodeState.VERIFYING)
            self.state_machine.transition(job, ReplacementCheckpoint.NODE_VERIFIED)
            await session.commit()

    async def _stage_node_verified(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            node = await self._require_node(session, job.node_id)
            credential = await self._require_credential(session, node.id)
            new_vps = await self._require_new_vps(session, job)
            deployment = await self._require_deployment(session, job)
            if job.is_dry_run:
                if job.master_snapshot is None:
                    job.master_snapshot = {
                        "id": node.master_node_id,
                        "name": node.name,
                        "scheme": "http",
                        "address": node.current_host,
                        "port": node.current_port,
                        "basePath": credential.panel_base_path or "",
                        "hasApiToken": bool(credential.api_token_ref),
                        "enable": True,
                        "allowPrivateAddress": False,
                        "tlsVerifyMode": "verify",
                        "pinnedCertSha256": "",
                        "inboundSyncMode": "all",
                        "inboundTags": [],
                        "outboundTag": "",
                    }
                self.state_machine.transition(job, ReplacementCheckpoint.MASTER_UPDATING)
                await session.commit()
                return
            master_id = self._parse_master_node_id(node)
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        existing = await self.master.get_node(master_id)
        if existing.transitive:
            raise ReplacementConfigurationError("transitive master nodes are read-only")
        if existing.tls_verify_mode == "mtls":
            raise ReplacementConfigurationError(
                "mTLS master nodes require certificate deployment support; "
                "refusing security downgrade"
            )
        if existing.has_api_token and not credential.api_token_ref:
            raise ReplacementConfigurationError(
                "old master node token reference is required for safe rollback before switching"
            )

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if job.master_snapshot is None:
                job.master_snapshot = existing.safe_snapshot()
            await session.commit()

        mutation = self._build_new_master_mutation(existing, new_vps, deployment)
        mutation = await self._prepare_pin_if_needed(mutation)
        test_result = await self.master.test_node(mutation)
        self._assert_master_test_result(test_result)

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            self.state_machine.transition(job, ReplacementCheckpoint.MASTER_UPDATING)
            await session.commit()

    async def _stage_master_updating(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if job.is_dry_run:
                job.master_updated_at = datetime.now(UTC)
                self.state_machine.transition(job, ReplacementCheckpoint.MASTER_UPDATED)
                await session.commit()
                return
            node = await self._require_node(session, job.node_id)
            new_vps = await self._require_new_vps(session, job)
            deployment = await self._require_deployment(session, job)
            snapshot = self._require_master_snapshot(job)
            master_id = self._parse_master_node_id(node)
            token = self._resolve_deployment_api_token(deployment)
            mutation = MasterNodeMutation.from_snapshot(snapshot, api_token=token)
            mutation = self._normalize_target_mutation(
                replace(
                    mutation,
                    scheme=self._deployment_scheme(deployment),
                    address=self._require_host(new_vps),
                    port=self._require_panel_port(deployment),
                    base_path=deployment.web_base_path or "",
                )
            )
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        mutation = await self._prepare_pin_if_needed(mutation)
        await self.master.update_node(master_id, mutation)

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            job.master_updated_at = datetime.now(UTC)
            await self._add_event(
                session, job, EventType.MASTER_UPDATED, "Master node configuration updated"
            )
            self.state_machine.transition(job, ReplacementCheckpoint.MASTER_UPDATED)
            await session.commit()

    async def _stage_master_updated(self, job_id: UUID, lease_token: str) -> None:
        del lease_token
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            self.state_machine.transition(job, ReplacementCheckpoint.MASTER_VERIFYING)
            await session.commit()

    async def _stage_master_verifying(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if job.is_dry_run:
                job.master_verified_at = datetime.now(UTC)
                self.state_machine.transition(job, ReplacementCheckpoint.MASTER_VERIFIED)
                await session.commit()
                return
            node = await self._require_node(session, job.node_id)
            new_vps = await self._require_new_vps(session, job)
            deployment = await self._require_deployment(session, job)
            snapshot = self._require_master_snapshot(job)
            master_id = self._parse_master_node_id(node)
            expected = MasterNodeMutation.from_snapshot(
                snapshot, api_token=self._resolve_deployment_api_token(deployment)
            )
            expected = self._normalize_target_mutation(
                replace(
                    expected,
                    scheme=self._deployment_scheme(deployment),
                    address=self._require_host(new_vps),
                    port=self._require_panel_port(deployment),
                    base_path=deployment.web_base_path or "",
                )
            )
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        expected = await self._prepare_pin_if_needed(expected)
        try:
            await self.master.verify_node(master_id, expected)
        except MasterTransientError:
            raise
        except MasterNodeVerificationError:
            await self._rollback_master(job_id)
            raise

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            job.master_verified_at = datetime.now(UTC)
            await self._add_event(
                session, job, EventType.MASTER_VERIFIED, "Master node update verified"
            )
            self.state_machine.transition(job, ReplacementCheckpoint.MASTER_VERIFIED)
            await session.commit()

    async def _stage_master_verified(self, job_id: UUID, lease_token: str) -> None:
        del lease_token
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            self.state_machine.transition(job, ReplacementCheckpoint.FINAL_CHECK)
            await session.commit()

    async def _stage_final_check(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            new_vps = await self._require_new_vps(session, job)
            host = self._require_host(new_vps)
            is_dry_run = job.is_dry_run
            await self._renew_lease_in_session(session, job_id, lease_token)
            await session.commit()

        if is_dry_run:
            decision = ReachabilityDecision.REACHABLE
        else:
            result = await self.reachability.verify(host)
            decision = result.decision
        if decision is ReachabilityDecision.INDETERMINATE:
            raise ReplacementDeferredError("final reachability check is indeterminate")
        if decision is ReachabilityDecision.UNREACHABLE:
            await self._rollback_master(job_id)
            raise SafetyViolationError("final reachability check failed; master rolled back")

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            job.final_health_verified_at = datetime.now(UTC)
            self.state_machine.transition(job, ReplacementCheckpoint.FINAL_VERIFIED)
            await session.commit()

    async def _stage_final_verified(self, job_id: UUID, lease_token: str) -> None:
        del lease_token
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            self.state_machine.transition(job, ReplacementCheckpoint.OLD_VPS_CLEANUP)
            await session.commit()

    async def _stage_old_vps_cleanup(self, job_id: UUID, lease_token: str) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            self._assert_not_emergency_stopped(dry_run=job.is_dry_run)
            new_vps = await self._require_new_vps(session, job)
            deployment = await self._require_deployment(session, job)
            if job.is_dry_run:
                provider = await self._require_provider(session, new_vps.provider_id)
                new_server_id = new_vps.provider_server_id
                await self._renew_lease_in_session(session, job_id, lease_token)
                await session.commit()
            else:
                if job.old_vps_instance_id is None:
                    raise SafetyViolationError("replacement job has no old VPS identity")
                old_vps = await VpsInstanceRepository(session).get(job.old_vps_instance_id)
                if old_vps is None:
                    raise SafetyViolationError("old VPS registry row is missing")
                if not self.settings.allow_old_vps_deletion:
                    raise ReplacementDeferredError(
                        "old VPS deletion is independently disabled; replacement is verified and "
                        "waiting at cleanup until an operator explicitly enables deletion"
                    )
                self.old_vps_guard.assert_can_delete(
                    job, deployment=deployment, new_vps=new_vps, old_vps=old_vps
                )
                provider = await self._require_provider(session, old_vps.provider_id)
                old_server_id = old_vps.provider_server_id
                await self._renew_lease_in_session(session, job_id, lease_token)
                await session.commit()

        adapter = self.provider_manager.get(provider, dry_run=job.is_dry_run)
        if job.is_dry_run:
            try:
                await self.provisioning.delete_temporary(adapter, new_server_id)
            except ProviderNotFoundError:
                pass
            async with self.database.session() as session:
                job = await self._require_job(session, job_id)
                new_vps = await self._require_new_vps(session, job)
                new_vps.state = VpsInstanceState.DELETED
                self.state_machine.transition(job, ReplacementCheckpoint.COMPLETED)
                await self._add_event(
                    session,
                    job,
                    EventType.REPLACEMENT_COMPLETED,
                    "Dry-run replacement simulation completed; old VPS and node registry unchanged",
                    payload={"dry_run": True},
                )
                await session.commit()
            return

        try:
            provider_old = await adapter.get_server(old_server_id)
        except ProviderNotFoundError:
            # Crash after a previously successful provider delete but before the DB commit is resumable.
            provider_old = None

        if provider_old is not None:
            if provider_old.provider_server_id != old_server_id:
                raise SafetyViolationError("provider returned a different old VPS identity")
            try:
                registered_ip = str(ipaddress.ip_address(old_vps.host or ""))
            except ValueError as exc:
                raise SafetyViolationError(
                    "old VPS deletion denied; registry host must be a literal public IP"
                ) from exc
            if provider_old.ipv4 != registered_ip:
                raise SafetyViolationError(
                    "old VPS deletion denied; provider IP does not match registry identity"
                )
            await adapter.delete_server(old_server_id)

        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            node = await self._require_node(session, job.node_id)
            credential = await self._require_credential(session, node.id)
            new_vps = await self._require_new_vps(session, job)
            deployment = await self._require_deployment(session, job)
            old_vps = await VpsInstanceRepository(session).get(job.old_vps_instance_id)
            if old_vps is None:
                raise SafetyViolationError("old VPS registry row vanished during cleanup")
            old_vps.state = VpsInstanceState.DELETED
            new_vps.role = VpsInstanceRole.CURRENT
            new_vps.state = VpsInstanceState.RUNNING
            job.old_vps_deleted_at = datetime.now(UTC)
            node.provider_id = new_vps.provider_id
            node.current_host = self._require_host(new_vps)
            node.current_port = self._require_panel_port(deployment)
            node.consecutive_failures = 0
            node.consecutive_successes = max(1, node.consecutive_successes or 0)
            credential.panel_username = deployment.panel_username
            credential.panel_base_path = deployment.web_base_path
            credential.panel_password_ref = deployment.panel_password_ref
            credential.panel_password_backend = SecretReferenceBackend.FILE
            credential.api_token_ref = deployment.api_token_ref
            credential.api_token_backend = SecretReferenceBackend.FILE
            if node.state is not NodeState.HEALTHY:
                NodeStateMachine.transition(node, NodeState.HEALTHY)
            await self._add_event(
                session, job, EventType.OLD_VPS_DELETED, "Old VPS deleted after all safety gates"
            )
            self.state_machine.transition(job, ReplacementCheckpoint.COMPLETED)
            await self._add_event(
                session, job, EventType.REPLACEMENT_COMPLETED, "Replacement completed successfully"
            )
            await session.commit()

    async def _rollback_master(self, job_id: UUID) -> None:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            if job.is_dry_run:
                return
            node = await self._require_node(session, job.node_id)
            credential = await self._require_credential(session, node.id)
            snapshot = self._require_master_snapshot(job)
            master_id = self._parse_master_node_id(node)
            has_token = bool(snapshot.get("hasApiToken"))
            old_token = None
            if has_token:
                if not credential.api_token_ref:
                    raise SafetyViolationError(
                        "cannot rollback master: old API token reference is missing"
                    )
                backend = credential.api_token_backend or credential.secret_backend
                old_token = self.secret_resolver.resolve(backend, credential.api_token_ref)
            mutation = MasterNodeMutation.from_snapshot(snapshot, api_token=old_token)
            await session.commit()
        await self.master.update_node(master_id, mutation)
        await self.master.verify_node(master_id, mutation)

    async def _fail_job(self, job_id: UUID, exc: Exception) -> None:
        async with self.database.session() as session:
            job = await ReplacementJobRepository(session).get(job_id)
            if job is None or job.checkpoint in _TERMINAL:
                return
            job.last_error_code = exc.__class__.__name__[:64]
            job.last_error_message = str(exc)[:2000]
            self.state_machine.transition(job, ReplacementCheckpoint.FAILED)
            node = await NodeRepository(session).get(job.node_id)
            if node is not None and not job.is_dry_run and node.state in {
                NodeState.REPLACING,
                NodeState.DEPLOYING,
                NodeState.VERIFYING,
            }:
                NodeStateMachine.transition(node, NodeState.FAILED)
            await self._add_event(
                session,
                job,
                EventType.REPLACEMENT_FAILED,
                "Replacement workflow failed; old VPS was not deleted",
                severity=EventSeverity.ERROR,
                payload={"error_code": job.last_error_code},
            )
            await session.commit()

    async def _acquire_lease(self, job_id: UUID, token: str) -> bool:
        now = datetime.now(UTC)
        async with self.database.session() as session:
            acquired = await ReplacementJobRepository(session).try_acquire_workflow_lease(
                job_id,
                token=token,
                now=now,
                lease_until=now + timedelta(seconds=self.settings.replacement_job_lease_seconds),
            )
            await session.commit()
            return acquired

    async def _release_lease(self, job_id: UUID, token: str) -> None:
        async with self.database.session() as session:
            await ReplacementJobRepository(session).release_workflow_lease(job_id, token=token)
            await session.commit()

    async def _renew_lease_in_session(self, session: Any, job_id: UUID, token: str) -> None:
        now = datetime.now(UTC)
        acquired = await ReplacementJobRepository(session).try_acquire_workflow_lease(
            job_id,
            token=token,
            now=now,
            lease_until=now + timedelta(seconds=self.settings.replacement_job_lease_seconds),
        )
        if not acquired:
            raise ReplacementBusyError("replacement workflow lease was lost")

    async def _get_checkpoint(self, job_id: UUID) -> ReplacementCheckpoint:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            return job.checkpoint or ReplacementCheckpoint.CREATED

    async def _require_job(self, session: Any, job_id: UUID) -> ReplacementJob:
        job = await ReplacementJobRepository(session).get(job_id)
        if job is None:
            raise ReplacementConfigurationError("replacement job does not exist")
        return job

    async def _require_node(self, session: Any, node_id: UUID) -> Node:
        node = await NodeRepository(session).get(node_id)
        if node is None:
            raise ReplacementConfigurationError("replacement node registry row is missing")
        return node

    async def _require_provider(self, session: Any, provider_id: UUID) -> Provider:
        provider = await ProviderRepository(session).get(provider_id)
        if provider is None or not provider.is_active:
            raise ReplacementConfigurationError("provider is missing or inactive")
        return provider

    async def _require_credential(self, session: Any, node_id: UUID) -> NodeCredential:
        credential = await NodeCredentialRepository(session).get_for_node(node_id)
        if credential is None:
            raise ReplacementConfigurationError("node credentials are not configured")
        return credential

    async def _require_new_vps(self, session: Any, job: ReplacementJob) -> VpsInstance:
        if job.new_vps_instance_id is None:
            raise ReplacementConfigurationError("replacement job has no new VPS")
        instance = await VpsInstanceRepository(session).get(job.new_vps_instance_id)
        if instance is None:
            raise ReplacementConfigurationError("replacement VPS registry row is missing")
        return instance

    async def _require_deployment(self, session: Any, job: ReplacementJob) -> Deployment:
        deployment = await DeploymentRepository(session).get_for_attempt(job.id, job.attempt_count)
        if deployment is None:
            raise ReplacementConfigurationError("deployment attempt registry row is missing")
        return deployment

    async def _add_event(
        self,
        session: Any,
        job: ReplacementJob,
        event_type: EventType,
        message: str,
        *,
        severity: EventSeverity = EventSeverity.INFO,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await EventRepository(session).add(
            Event(
                node_id=job.node_id,
                replacement_job_id=job.id,
                event_type=event_type,
                severity=severity,
                message=message,
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )

    def _build_create_request(
        self,
        job: ReplacementJob,
        node: Node,
        provider: Provider,
        credential: NodeCredential,
        old_vps: VpsInstance,
    ) -> CreateServerRequest:
        region = old_vps.region or provider.default_region
        server_type = old_vps.server_type or provider.default_server_type
        image = old_vps.image or provider.default_image
        missing = [
            key
            for key, value in (
                ("region", region),
                ("server_type", server_type),
                ("image", image),
            )
            if not value
        ]
        if missing:
            raise ReplacementConfigurationError(
                "node replacement template is incomplete: " + ", ".join(missing)
            )

        ssh_keys: tuple[str, ...] = ()
        root_password = None
        if credential.ssh_auth_method is SshAuthMethod.PRIVATE_KEY:
            if not credential.ssh_public_key:
                raise ReplacementConfigurationError(
                    "private-key SSH replacement requires node_credentials.ssh_public_key"
                )
            ssh_keys = (credential.ssh_public_key,)
        elif credential.ssh_auth_method is SshAuthMethod.PASSWORD:
            if provider.provider_type is not ProviderType.LINODE:
                raise ReplacementConfigurationError(
                    "password SSH bootstrap is currently supported only for Linode; "
                    "use a public key"
                )
            root_password = self.secret_resolver.resolve(
                credential.secret_backend, credential.ssh_secret_ref
            )
        else:
            raise ReplacementConfigurationError("unsupported SSH authentication method")

        return CreateServerRequest(
            name=self._replacement_server_name(node, job),
            region=str(region),
            server_type=str(server_type),
            image=str(image),
            ssh_public_keys=ssh_keys,
            root_password=root_password,
            labels={
                "managed-by": "aso-node-recovery",
                "replacement-job": job.id.hex[:12],
                "attempt": str(job.attempt_count),
            },
        )

    @staticmethod
    def _replacement_server_name(node: Node, job: ReplacementJob) -> str:
        safe = re.sub(r"[^a-z0-9-]+", "-", node.name.lower()).strip("-") or "node"
        safe = safe[:32].rstrip("-")
        return f"aso-{safe}-{job.id.hex[:8]}-a{job.attempt_count}"[:63]

    def _build_new_master_mutation(
        self, existing: Any, new_vps: VpsInstance, deployment: Deployment
    ) -> MasterNodeMutation:
        mutation = MasterNodeMutation.from_existing(
            existing,
            scheme=self._deployment_scheme(deployment),
            address=self._require_host(new_vps),
            port=self._require_panel_port(deployment),
            base_path=deployment.web_base_path or "",
            api_token=self._resolve_deployment_api_token(deployment),
        )
        return mutation

    @staticmethod
    def _normalize_target_mutation(mutation: MasterNodeMutation) -> MasterNodeMutation:
        if mutation.scheme != "https":
            return replace(
                mutation, tls_verify_mode="verify", pinned_cert_sha256=""
            )
        return mutation

    async def _prepare_pin_if_needed(self, mutation: MasterNodeMutation) -> MasterNodeMutation:
        if mutation.scheme == "https" and mutation.tls_verify_mode == "pin":
            fingerprint = await self.master.certificate_fingerprint(
                replace(mutation, pinned_cert_sha256="")
            )
            return replace(mutation, pinned_cert_sha256=fingerprint)
        return mutation

    @staticmethod
    def _assert_master_test_result(result: dict[str, Any]) -> None:
        status = str(result.get("status") or "").lower()
        xray_state = str(result.get("xrayState") or "").lower()
        if status and status != "online":
            raise MasterNodeVerificationError(f"master preflight reports status={status!r}")
        if xray_state and xray_state != "running":
            raise MasterNodeVerificationError(
                f"master preflight reports xrayState={xray_state!r}"
            )

    def _resolve_deployment_api_token(self, deployment: Deployment):
        if not deployment.api_token_ref:
            raise ReplacementConfigurationError("deployment API token reference is missing")
        return self.secret_resolver.resolve(SecretReferenceBackend.FILE, deployment.api_token_ref)

    @staticmethod
    def _deployment_scheme(deployment: Deployment) -> str:
        if not deployment.access_url:
            raise ReplacementConfigurationError("deployment access URL is missing")
        scheme = urlsplit(deployment.access_url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ReplacementConfigurationError("deployment access URL has unsupported scheme")
        return scheme

    @staticmethod
    def _require_panel_port(deployment: Deployment) -> int:
        if deployment.panel_port is None or not 1 <= deployment.panel_port <= 65535:
            raise ReplacementConfigurationError("deployment panel port is missing/invalid")
        return deployment.panel_port

    @staticmethod
    def _require_host(vps: VpsInstance) -> str:
        if not vps.host:
            raise ReplacementConfigurationError("replacement VPS has no public host")
        return vps.host

    @staticmethod
    def _require_master_snapshot(job: ReplacementJob) -> dict[str, Any]:
        if not isinstance(job.master_snapshot, dict):
            raise ReplacementConfigurationError("master rollback snapshot is missing")
        return dict(job.master_snapshot)

    @staticmethod
    def _parse_master_node_id(node: Node) -> int:
        try:
            value = int(node.master_node_id)
        except (TypeError, ValueError) as exc:
            raise ReplacementConfigurationError(
                "master_node_id must be the explicit numeric 3X-UI node id"
            ) from exc
        if value <= 0:
            raise ReplacementConfigurationError("master_node_id must be positive")
        return value

    @staticmethod
    def _map_vps_state(status: ProviderServerStatus) -> VpsInstanceState:
        mapping = {
            ProviderServerStatus.PROVISIONING: VpsInstanceState.PROVISIONING,
            ProviderServerStatus.RUNNING: VpsInstanceState.RUNNING,
            ProviderServerStatus.OFFLINE: VpsInstanceState.ERROR,
            ProviderServerStatus.DELETING: VpsInstanceState.DELETING,
            ProviderServerStatus.DELETED: VpsInstanceState.DELETED,
            ProviderServerStatus.ERROR: VpsInstanceState.ERROR,
            ProviderServerStatus.UNKNOWN: VpsInstanceState.PROVISIONING,
        }
        return mapping[status]

    async def _assert_runtime_execution_allowed(self, job_dry_run: bool) -> None:
        if job_dry_run or self.operational_settings is None:
            return
        if await self.operational_settings.effective_dry_run(self.settings):
            raise ReplacementDeferredError(
                "live replacement paused because runtime execution is now DRY_RUN"
            )

    async def _job_is_dry_run(self, job_id: UUID) -> bool:
        async with self.database.session() as session:
            job = await self._require_job(session, job_id)
            return bool(job.is_dry_run)

    def _assert_not_emergency_stopped(self, *, dry_run: bool = False) -> None:
        # The emergency stop is a hard gate for real infrastructure mutation. Safe simulations are
        # still allowed so operators can validate workflows while production remains locked.
        if self.settings.replacement_emergency_stop and not dry_run:
            raise ReplacementDeferredError("replacement emergency stop is enabled")

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
