from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Awaitable, Callable, TypeVar

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.secrets import SecretResolver
from app.database import Database
from app.deployment.node_api import ThreeXUiNodeApiVerifier
from app.master.factory import Master3XUiClientFactory
from app.master.types import MasterNode
from app.models import Node, Provider
from app.monitoring.check_host import CheckHostClient
from app.registry.discovery import ReadOnlyProviderFactory

_T = TypeVar("_T")


class ApiHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class ApiHealthResult:
    key: str
    label: str
    category: str
    status: ApiHealthStatus
    latency_ms: int | None
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is ApiHealthStatus.HEALTHY


@dataclass(frozen=True, slots=True)
class ApiHealthReport:
    results: tuple[ApiHealthResult, ...]

    @property
    def healthy_count(self) -> int:
        return sum(item.status is ApiHealthStatus.HEALTHY for item in self.results)

    @property
    def failed_count(self) -> int:
        return sum(item.status is ApiHealthStatus.FAILED for item in self.results)

    @property
    def degraded_count(self) -> int:
        return sum(item.status is ApiHealthStatus.DEGRADED for item in self.results)


class ApiHealthService:
    """Read-only external dependency diagnostics.

    Health checks never call provider mutation APIs, Master update APIs, replacement workflows, or
    infrastructure cleanup. Provider and node credentials are resolved only long enough to perform
    authenticated read/status requests and are never included in results or logs.
    """

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        check_host: CheckHostClient | None = None,
        secret_resolver: SecretResolver | None = None,
        provider_factory: ReadOnlyProviderFactory | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.check_host = check_host or CheckHostClient(
            base_url=settings.check_host_base_url,
            timeout_seconds=settings.api_health_timeout_seconds,
        )
        self._owns_check_host = check_host is None
        self.secret_resolver = secret_resolver or SecretResolver()
        self.provider_factory = provider_factory or ReadOnlyProviderFactory(settings)
        self._semaphore = asyncio.Semaphore(settings.api_health_max_concurrency)

    async def aclose(self) -> None:
        if self._owns_check_host:
            await self.check_host.aclose()

    async def check_all(self) -> ApiHealthReport:
        core, providers, nodes = await asyncio.gather(
            self.check_core(),
            self.check_providers(),
            self.check_nodes(),
        )
        return ApiHealthReport(results=tuple((*core, *providers, *nodes)))

    async def check_core(self) -> tuple[ApiHealthResult, ...]:
        database, check_host, master, telegram = await asyncio.gather(
            self.check_database(),
            self.check_check_host(),
            self.check_master(),
            self.check_telegram(),
        )
        return database, check_host, master, telegram

    async def check_database(self) -> ApiHealthResult:
        async def probe() -> str:
            async with self.database.engine.connect() as connection:
                value = await connection.scalar(text("SELECT 1"))
            if value != 1:
                raise RuntimeError("database health query returned an unexpected value")
            return "connected; SELECT 1 succeeded"

        return await self._timed("database", "PostgreSQL", "core", probe)

    async def check_check_host(self) -> ApiHealthResult:
        async def probe() -> str:
            nodes = await self.check_host.resolve_nodes(
                configured_nodes=self.settings.check_host_nodes,
                country_code=self.settings.check_host_country_code,
                max_nodes=self.settings.check_host_max_nodes,
            )
            return (
                f"API reachable; {len(nodes)} node(s) available for "
                f"{self.settings.check_host_country_code.upper()} checks"
            )

        return await self._timed("check-host", "Check-Host", "core", probe)

    async def check_master(self) -> ApiHealthResult:
        if not self.settings.master_3xui_base_url:
            return self._not_configured(
                "master-3xui", "3X-UI Master", "core", "Master API is not configured"
            )

        async def probe() -> str:
            client = Master3XUiClientFactory.create(self.settings)
            try:
                nodes = await client.list_nodes()
                route = client.connection_route
            finally:
                await client.aclose()
            return f"authenticated via {route}; {len(nodes)} Master node(s) visible"

        return await self._timed("master-3xui", "3X-UI Master", "core", probe)

    async def check_telegram(self) -> ApiHealthResult:
        if self.settings.telegram_bot_token is None:
            return self._not_configured(
                "telegram", "Telegram Bot API", "core", "bot token is not configured"
            )

        async def probe() -> str:
            token = self.settings.telegram_bot_token.get_secret_value()
            url = f"https://api.telegram.org/bot{token}/getMe"
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.settings.api_health_timeout_seconds)
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise RuntimeError("Telegram Bot API getMe request failed") from exc
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise RuntimeError("Telegram getMe did not return ok=true")
            result = payload.get("result")
            username = result.get("username") if isinstance(result, dict) else None
            return f"authenticated as @{username}" if username else "bot token authenticated"

        return await self._timed("telegram", "Telegram Bot API", "core", probe)

    async def check_providers(self) -> tuple[ApiHealthResult, ...]:
        async with self.database.session() as session:
            providers = list((await session.scalars(select(Provider).order_by(Provider.key))).all())
        if not providers:
            return (
                self._not_configured(
                    "providers", "Providers", "provider", "no providers are registered"
                ),
            )
        return tuple(await asyncio.gather(*(self._check_provider(provider) for provider in providers)))

    async def _check_provider(self, provider: Provider) -> ApiHealthResult:
        async def probe() -> str:
            credential = self.secret_resolver.resolve(
                provider.credential_backend,
                provider.credential_ref,
            )
            adapter = self.provider_factory.create(provider.provider_type, credential)
            try:
                await adapter.probe_access()
            finally:
                await adapter.aclose()
            state = "active" if provider.is_active else "disabled in ASO"
            return f"authenticated; read access works; {state}"

        return await self._timed(
            f"provider:{provider.id}",
            f"{provider.display_name} ({provider.provider_type.value})",
            "provider",
            probe,
        )

    async def check_nodes(self) -> tuple[ApiHealthResult, ...]:
        async with self.database.session() as session:
            nodes = list(
                (
                    await session.scalars(
                        select(Node)
                        .options(selectinload(Node.credentials))
                        .order_by(Node.name)
                    )
                ).all()
            )
        if not nodes:
            return (
                self._not_configured("nodes", "Node APIs", "node", "no nodes are registered"),
            )

        master_nodes: dict[int, MasterNode] = {}
        master_error: Exception | None = None
        if self.settings.master_3xui_base_url:
            client = Master3XUiClientFactory.create(self.settings)
            try:
                listed = await self._with_timeout(client.list_nodes())
                master_nodes = {item.id: item for item in listed}
            except Exception as exc:  # isolated into per-node health results below
                master_error = exc
            finally:
                await client.aclose()
        else:
            master_error = RuntimeError("Master API is not configured")

        return tuple(
            await asyncio.gather(
                *(self._check_node(node, master_nodes, master_error) for node in nodes)
            )
        )

    async def _check_node(
        self,
        node: Node,
        master_nodes: dict[int, MasterNode],
        master_error: Exception | None,
    ) -> ApiHealthResult:
        credential = node.credentials
        if credential is None or not credential.api_token_ref or credential.api_token_backend is None:
            return self._not_configured(
                f"node:{node.id}",
                f"Node {node.name}",
                "node",
                "node API token is not configured",
            )

        try:
            master_id = int(node.master_node_id)
        except ValueError:
            return ApiHealthResult(
                key=f"node:{node.id}",
                label=f"Node {node.name}",
                category="node",
                status=ApiHealthStatus.FAILED,
                latency_ms=None,
                detail="Master node ID is invalid",
            )

        master_node = master_nodes.get(master_id)
        if master_node is None:
            detail = "Master node endpoint could not be resolved"
            if master_error is not None:
                detail += f": {self._safe_error(master_error)}"
            return ApiHealthResult(
                key=f"node:{node.id}",
                label=f"Node {node.name}",
                category="node",
                status=ApiHealthStatus.FAILED,
                latency_ms=None,
                detail=detail,
            )

        async def probe() -> str:
            token = self.secret_resolver.resolve(
                credential.api_token_backend,
                credential.api_token_ref,
            )
            verifier = ThreeXUiNodeApiVerifier(
                timeout_seconds=self.settings.api_health_timeout_seconds,
                verify_tls=self.settings.three_xui_verify_tls,
            )
            payload = await verifier.verify_access_url(self._node_access_url(master_node), token)
            version = payload.get("version") or payload.get("xrayVersion")
            return f"authenticated; Xray running{f'; version={version}' if version else ''}"

        return await self._timed(
            f"node:{node.id}",
            f"Node {node.name}",
            "node",
            probe,
        )

    async def _timed(
        self,
        key: str,
        label: str,
        category: str,
        probe: Callable[[], Awaitable[str]],
    ) -> ApiHealthResult:
        started = monotonic()
        try:
            async with self._semaphore:
                detail = await self._with_timeout(probe())
        except asyncio.TimeoutError:
            return ApiHealthResult(
                key=key,
                label=label,
                category=category,
                status=ApiHealthStatus.FAILED,
                latency_ms=self._elapsed_ms(started),
                detail=f"timeout after {self.settings.api_health_timeout_seconds:g}s",
            )
        except Exception as exc:
            return ApiHealthResult(
                key=key,
                label=label,
                category=category,
                status=ApiHealthStatus.FAILED,
                latency_ms=self._elapsed_ms(started),
                detail=self._safe_error(exc),
            )
        return ApiHealthResult(
            key=key,
            label=label,
            category=category,
            status=ApiHealthStatus.HEALTHY,
            latency_ms=self._elapsed_ms(started),
            detail=detail,
        )

    async def _with_timeout(self, awaitable: Awaitable[_T]) -> _T:
        return await asyncio.wait_for(awaitable, timeout=self.settings.api_health_timeout_seconds)

    @staticmethod
    def _node_access_url(master: MasterNode) -> str:
        scheme = master.scheme.strip().lower() or "http"
        base_path = master.base_path.strip()
        if base_path and not base_path.startswith("/"):
            base_path = "/" + base_path
        return f"{scheme}://{master.address.strip()}:{master.port}{base_path.rstrip('/')}"

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int((monotonic() - started) * 1000))

    @staticmethod
    def _not_configured(key: str, label: str, category: str, detail: str) -> ApiHealthResult:
        return ApiHealthResult(
            key=key,
            label=label,
            category=category,
            status=ApiHealthStatus.NOT_CONFIGURED,
            latency_ms=None,
            detail=detail,
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = " ".join(str(exc).split())
        if not message:
            message = type(exc).__name__
        return f"{type(exc).__name__}: {message}"[:220]
