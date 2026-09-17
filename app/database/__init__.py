"""Database metadata foundation.

Connection/session management and repository implementations are intentionally deferred to Patch 02.
"""

from app.database.base import Base, metadata

__all__ = ["Base", "metadata"]
