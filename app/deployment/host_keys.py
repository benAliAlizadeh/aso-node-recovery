from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class SshHostKeyCandidate:
    host: str
    port: int
    algorithm: str
    fingerprint: str
    known_hosts_entry: str


class AsyncSshHostKeyTrustService:
    """Fetch and persist SSH host keys without weakening strict verification."""

    def __init__(self, known_hosts_path: str, *, timeout_seconds: float = 10.0) -> None:
        self.path = Path(known_hosts_path).expanduser()
        self.timeout_seconds = timeout_seconds

    async def inspect(self, host: str, port: int) -> SshHostKeyCandidate:
        host = host.strip()
        if not host:
            raise ValueError("SSH host cannot be blank")
        if not 1 <= port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535")

        asyncssh = importlib.import_module("asyncssh")
        try:
            key = await asyncio.wait_for(
                asyncssh.get_server_host_key(
                    host,
                    port=port,
                    connect_timeout=self.timeout_seconds,
                ),
                timeout=self.timeout_seconds + 1.0,
            )
        except TimeoutError as exc:
            raise TimeoutError(f"SSH host-key probe timed out for {host}:{port}") from exc
        except Exception as exc:
            raise ConnectionError(f"SSH host-key probe failed for {host}:{port}: {exc}") from exc

        if key is None:
            raise ConfigurationError(f"SSH server {host}:{port} did not present a host key")

        algorithm = key.algorithm.decode("ascii") if isinstance(key.algorithm, bytes) else str(key.algorithm)
        fingerprint = str(key.get_fingerprint("sha256"))
        exported = key.export_public_key("openssh").decode("ascii").strip()
        host_token = host if port == 22 else f"[{host}]:{port}"
        return SshHostKeyCandidate(
            host=host,
            port=port,
            algorithm=algorithm,
            fingerprint=fingerprint,
            known_hosts_entry=f"{host_token} {exported}\n",
        )

    async def trust(
        self,
        host: str,
        port: int,
        *,
        expected_fingerprint: str,
    ) -> SshHostKeyCandidate:
        candidate = await self.inspect(host, port)
        if candidate.fingerprint != expected_fingerprint:
            raise ConfigurationError(
                "SSH host key changed before confirmation; refusing to trust it. "
                f"Expected {expected_fingerprint}, received {candidate.fingerprint}."
            )
        self._write_candidate(candidate)
        return candidate

    def _write_candidate(self, candidate: SshHostKeyCandidate) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(parent, 0o700)
        except OSError as exc:
            raise ConfigurationError("SSH known_hosts directory cannot be secured") from exc

        host_token = candidate.host if candidate.port == 22 else f"[{candidate.host}]:{candidate.port}"
        existing: list[str] = []
        if self.path.exists():
            try:
                existing = self.path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise ConfigurationError("SSH known_hosts file cannot be read") from exc

        kept = [
            line
            for line in existing
            if not line.strip()
            or line.lstrip().startswith("#")
            or line.split(maxsplit=1)[0] != host_token
        ]
        kept.append(candidate.known_hosts_entry.rstrip("\n"))
        payload = "\n".join(kept).rstrip("\n") + "\n"

        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
