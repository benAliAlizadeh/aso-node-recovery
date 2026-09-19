from __future__ import annotations

from app.core.config import Settings
from app.core.secrets import SecretResolver
from app.deployment.types import SshConnectionSpec
from app.models.node import NodeCredential


class NodeSshSpecFactory:
    """Turn persisted non-secret SSH metadata + secret reference into a runtime connection spec."""

    def __init__(self, settings: Settings, secret_resolver: SecretResolver | None = None) -> None:
        self.settings = settings
        self.secret_resolver = secret_resolver or SecretResolver()

    def create(self, credential: NodeCredential, *, host: str) -> SshConnectionSpec:
        secret = self.secret_resolver.resolve(
            credential.secret_backend, credential.ssh_secret_ref
        )
        return SshConnectionSpec(
            host=host,
            port=credential.ssh_port,
            username=credential.ssh_username,
            auth_method=credential.ssh_auth_method,
            secret=secret,
            verify_host_key=self.settings.ssh_verify_host_key,
            known_hosts=self.settings.effective_ssh_known_hosts_path,
        )
