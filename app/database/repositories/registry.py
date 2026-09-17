from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, update

from app.database.repositories.base import SqlAlchemyRepository
from app.models import (
    Deployment,
    Event,
    Node,
    NodeCheck,
    NodeCredential,
    Provider,
    ReplacementJob,
    SystemSetting,
    VpsInstance,
)


class ProviderRepository(SqlAlchemyRepository[Provider]):
    model = Provider

    async def get_by_key(self, key: str) -> Provider | None:
        return await self.session.scalar(select(Provider).where(Provider.key == key))


class NodeRepository(SqlAlchemyRepository[Node]):
    model = Node

    def monitoring_query(self) -> Select[tuple[Node]]:
        return select(Node).where(Node.monitoring_enabled.is_(True)).order_by(Node.name)

    async def list_monitoring_enabled(self) -> list[Node]:
        return list((await self.session.scalars(self.monitoring_query())).all())

    async def list_failed(self, *, limit: int = 100) -> list[Node]:
        from app.models import NodeState

        query = select(Node).where(Node._state == NodeState.FAILED).order_by(Node.name).limit(limit)
        return list((await self.session.scalars(query)).all())

    async def try_acquire_monitoring_lease(
        self,
        node_id: UUID,
        *,
        token: str,
        now: datetime,
        lease_until: datetime,
    ) -> bool:
        statement = (
            update(Node)
            .where(
                Node.id == node_id,
                Node.monitoring_enabled.is_(True),
                or_(Node.monitoring_lease_until.is_(None), Node.monitoring_lease_until <= now),
            )
            .values(monitoring_lease_token=token, monitoring_lease_until=lease_until)
        )
        result = await self.session.execute(statement)
        return bool(result.rowcount == 1)

    async def release_monitoring_lease(self, node_id: UUID, *, token: str) -> None:
        await self.session.execute(
            update(Node)
            .where(Node.id == node_id, Node.monitoring_lease_token == token)
            .values(monitoring_lease_token=None, monitoring_lease_until=None)
        )


class NodeCredentialRepository(SqlAlchemyRepository[NodeCredential]):
    model = NodeCredential

    async def get_for_node(self, node_id: UUID) -> NodeCredential | None:
        return await self.session.scalar(
            select(NodeCredential).where(NodeCredential.node_id == node_id)
        )


class NodeCheckRepository(SqlAlchemyRepository[NodeCheck]):
    model = NodeCheck

    async def recent_for_node(self, node_id: UUID, *, limit: int = 20) -> list[NodeCheck]:
        query = (
            select(NodeCheck)
            .where(NodeCheck.node_id == node_id)
            .order_by(NodeCheck.checked_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(query)).all())


class ReplacementJobRepository(SqlAlchemyRepository[ReplacementJob]):
    model = ReplacementJob

    async def get_active_for_node(self, node_id: UUID) -> ReplacementJob | None:
        return await self.session.scalar(
            select(ReplacementJob).where(
                and_(ReplacementJob.node_id == node_id, ReplacementJob.active_slot.is_(True))
            )
        )

    async def count_active(self) -> int:
        value = await self.session.scalar(
            select(func.count()).select_from(ReplacementJob).where(
                ReplacementJob.active_slot.is_(True)
            )
        )
        return int(value or 0)

    async def list_active(self, *, limit: int = 100) -> list[ReplacementJob]:
        query = (
            select(ReplacementJob)
            .where(ReplacementJob.active_slot.is_(True))
            .order_by(ReplacementJob.created_at)
            .limit(limit)
        )
        return list((await self.session.scalars(query)).all())

    async def latest_for_node(self, node_id: UUID) -> ReplacementJob | None:
        return await self.session.scalar(
            select(ReplacementJob)
            .where(ReplacementJob.node_id == node_id)
            .order_by(ReplacementJob.created_at.desc())
            .limit(1)
        )

    async def try_acquire_workflow_lease(
        self,
        job_id: UUID,
        *,
        token: str,
        now: datetime,
        lease_until: datetime,
    ) -> bool:
        statement = (
            update(ReplacementJob)
            .where(
                ReplacementJob.id == job_id,
                ReplacementJob.active_slot.is_(True),
                or_(
                    ReplacementJob.workflow_lease_until.is_(None),
                    ReplacementJob.workflow_lease_until <= now,
                    ReplacementJob.workflow_lease_token == token,
                ),
            )
            .values(workflow_lease_token=token, workflow_lease_until=lease_until)
        )
        result = await self.session.execute(statement)
        return bool(result.rowcount == 1)

    async def release_workflow_lease(self, job_id: UUID, *, token: str) -> None:
        await self.session.execute(
            update(ReplacementJob)
            .where(
                ReplacementJob.id == job_id,
                ReplacementJob.workflow_lease_token == token,
            )
            .values(workflow_lease_token=None, workflow_lease_until=None)
        )


class VpsInstanceRepository(SqlAlchemyRepository[VpsInstance]):
    model = VpsInstance

    async def get_current_for_node(self, node_id: UUID) -> VpsInstance | None:
        from app.models import VpsInstanceRole, VpsInstanceState

        return await self.session.scalar(
            select(VpsInstance)
            .where(
                VpsInstance.node_id == node_id,
                VpsInstance.role == VpsInstanceRole.CURRENT,
                VpsInstance.state != VpsInstanceState.DELETED,
            )
            .order_by(VpsInstance.created_at.desc())
        )

    async def count_active_replacements(self) -> int:
        from app.models import VpsInstanceRole, VpsInstanceState

        value = await self.session.scalar(
            select(func.count()).select_from(VpsInstance).where(
                VpsInstance.role == VpsInstanceRole.REPLACEMENT,
                VpsInstance.state != VpsInstanceState.DELETED,
            )
        )
        return int(value or 0)

    async def get_by_provider_identity(
        self, provider_id: UUID, provider_server_id: str
    ) -> VpsInstance | None:
        return await self.session.scalar(
            select(VpsInstance).where(
                VpsInstance.provider_id == provider_id,
                VpsInstance.provider_server_id == provider_server_id,
            )
        )


class DeploymentRepository(SqlAlchemyRepository[Deployment]):
    model = Deployment

    async def get_for_attempt(self, job_id: UUID, attempt_number: int) -> Deployment | None:
        return await self.session.scalar(
            select(Deployment).where(
                Deployment.replacement_job_id == job_id,
                Deployment.attempt_number == attempt_number,
            )
        )

    async def latest_for_job(self, job_id: UUID) -> Deployment | None:
        return await self.session.scalar(
            select(Deployment)
            .where(Deployment.replacement_job_id == job_id)
            .order_by(Deployment.attempt_number.desc())
            .limit(1)
        )


class EventRepository(SqlAlchemyRepository[Event]):
    model = Event

    async def recent_for_node(self, node_id: UUID, *, limit: int = 100) -> list[Event]:
        query = (
            select(Event)
            .where(Event.node_id == node_id)
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(query)).all())


class SettingRepository(SqlAlchemyRepository[SystemSetting]):
    model = SystemSetting

    async def get_by_key(self, key: str) -> SystemSetting | None:
        return await self.session.scalar(select(SystemSetting).where(SystemSetting.key == key))
