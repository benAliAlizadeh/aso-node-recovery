from __future__ import annotations

import os
from pathlib import Path

from pydantic import SecretStr

from app.core.errors import ConfigurationError
from app.models.enums import SecretReferenceBackend


class SecretResolver:
    """Resolve secret references without storing plaintext in database models.

    Only environment and file references are implemented in this milestone. External secret stores
    and database-encrypted secrets remain explicit future integrations rather than silent fallbacks.
    """

    def resolve(self, backend: SecretReferenceBackend, reference: str) -> SecretStr:
        if not reference.strip():
            raise ConfigurationError("secret reference cannot be blank")

        if backend is SecretReferenceBackend.ENVIRONMENT:
            value = os.getenv(reference)
            if value is None or value == "":
                raise ConfigurationError(f"secret environment reference is not configured: {reference}")
            return SecretStr(value)

        if backend is SecretReferenceBackend.FILE:
            path = Path(reference).expanduser()
            try:
                value = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigurationError(f"secret file reference cannot be read: {reference}") from exc
            if not value:
                raise ConfigurationError(f"secret file reference is empty: {reference}")
            return SecretStr(value)

        raise ConfigurationError(
            f"secret backend {backend.value!r} is not implemented in this milestone"
        )
