from __future__ import annotations

import asyncio
import importlib
from typing import Protocol

from app.core.errors import ConfigurationError
from app.deployment.types import CommandResult, SshConnectionSpec
from app.models.enums import SshAuthMethod


class RemoteCommandExecutor(Protocol):
    async def run(
        self, spec: SshConnectionSpec, command: str, *, timeout_seconds: float | None = None
    ) -> CommandResult: ...


class AsyncSshCommandExecutor:
    """AsyncSSH-backed command execution with no stdout/stderr logging."""

    async def run(
        self, spec: SshConnectionSpec, command: str, *, timeout_seconds: float | None = None
    ) -> CommandResult:
        asyncssh = importlib.import_module("asyncssh")
        options: dict[str, object] = {
            "host": spec.host,
            "port": spec.port,
            "username": spec.username,
        }
        if spec.verify_host_key:
            # None lets AsyncSSH use its normal known_hosts behavior. A custom file can be supplied
            # for newly provisioned hosts once a trusted key has been seeded.
            if spec.known_hosts is not None:
                options["known_hosts"] = spec.known_hosts
        else:
            options["known_hosts"] = None

        secret_value = spec.secret.get_secret_value()
        if spec.auth_method is SshAuthMethod.PASSWORD:
            options["password"] = secret_value
        elif spec.auth_method is SshAuthMethod.PRIVATE_KEY:
            if "PRIVATE KEY" in secret_value:
                options["client_keys"] = [asyncssh.import_private_key(secret_value)]
            else:
                options["client_keys"] = [secret_value]
        else:
            raise ConfigurationError(f"unsupported SSH auth method: {spec.auth_method}")

        async def execute() -> CommandResult:
            async with asyncssh.connect(**options) as connection:
                result = await connection.run(command, check=False)
                return CommandResult(
                    stdout=str(result.stdout or ""),
                    stderr=str(result.stderr or ""),
                    exit_status=int(result.exit_status),
                )

        if timeout_seconds is None:
            return await execute()
        return await asyncio.wait_for(execute(), timeout=timeout_seconds)


class SshReadinessProbe:
    def __init__(
        self,
        executor: RemoteCommandExecutor,
        *,
        timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 3.0,
        per_attempt_timeout_seconds: float = 10.0,
    ) -> None:
        self.executor = executor
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.per_attempt_timeout_seconds = per_attempt_timeout_seconds

    async def wait(self, spec: SshConnectionSpec) -> None:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        last_error: BaseException | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                result = await self.executor.run(
                    spec,
                    "printf ASO_SSH_READY",
                    timeout_seconds=self.per_attempt_timeout_seconds,
                )
                if result.exit_status == 0 and result.stdout == "ASO_SSH_READY":
                    return
            except ConfigurationError:
                raise
            except Exception as exc:  # external SSH exception types vary
                last_error = exc
            await asyncio.sleep(self.poll_interval_seconds)
        message = "SSH did not become ready within the configured timeout"
        if last_error is not None:
            raise TimeoutError(message) from last_error
        raise TimeoutError(message)
