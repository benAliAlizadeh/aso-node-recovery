from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import blake2b
from typing import AsyncIterator

from sqlalchemy import text

from app.database import Database


class PostgresGlobalReplacementLock:
    """Short-lived global advisory lock for atomic replacement admission/slot allocation."""

    def __init__(self, database: Database, *, namespace: str = "aso-node-recovery:admission") -> None:
        self.database = database
        raw = blake2b(namespace.encode(), digest_size=8).digest()
        self.key = int.from_bytes(raw, byteorder="big", signed=True)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[bool]:
        async with self.database.engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": self.key}
                    )
