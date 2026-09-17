from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, or_, select, update

from app.database.repositories.base import SqlAlchemyRepository
from app.models import (
    Deployment,
    Event,
    Node,
    NodeCheck,
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


class VpsInstanceRepository(SqlAlchemyRepository[VpsInstance]):
    model = VpsInstance

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
