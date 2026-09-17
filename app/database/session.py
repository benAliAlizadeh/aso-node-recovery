from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.errors import ConfigurationError


class Database:
    """Owns the async SQLAlchemy engine/session factory without global mutable state."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        if not database_url.strip():
            raise ConfigurationError("database_url is required")
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        if settings.database_url is None:
            raise ConfigurationError("ASO_DATABASE_URL is required for database access")
        return cls(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
