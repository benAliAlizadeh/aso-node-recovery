from __future__ import annotations

import os
import tempfile
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


class RuntimeSecretStore:
    """Small file-backed sink for generated runtime secrets.

    Secret bytes are written atomically with owner-only permissions. Database rows store only the
    returned file reference. The directory should be placed on persistent encrypted storage in
    production and included in backup/restore policy.
    """

    def __init__(self, directory: str) -> None:
        self.directory = Path(directory).expanduser().resolve()

    def write(self, scope: str, name: str, value: SecretStr) -> str:
        safe_scope = "".join(ch for ch in scope if ch.isalnum() or ch in {"-", "_"})
        safe_name = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_"})
        if not safe_scope or not safe_name:
            raise ConfigurationError("runtime secret scope/name contains no safe characters")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.directory, 0o700)
        except OSError as exc:
            raise ConfigurationError("runtime secret directory permissions cannot be secured") from exc

        target = self.directory / f"{safe_scope}--{safe_name}.secret"
        fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(value.get_secret_value())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
            os.chmod(target, 0o600)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        return str(target)

    def delete_reference(self, reference: str | None) -> None:
        if not reference:
            return
        path = Path(reference).expanduser().resolve()
        try:
            path.relative_to(self.directory)
        except ValueError as exc:
            raise ConfigurationError("refusing to delete a runtime secret outside configured directory") from exc
        try:
            path.unlink()
        except FileNotFoundError:
            pass
