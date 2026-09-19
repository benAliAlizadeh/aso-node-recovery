from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.deployment.host_keys import load_trusted_host_key_fingerprint
from app.deployment.ssh import AsyncSshCommandExecutor
from app.deployment.types import SshConnectionSpec
from app.models.enums import SshAuthMethod


class FakeKey:
    algorithm = b"ssh-ed25519"

    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def get_fingerprint(self, hash_name: str = "sha256") -> str:
        assert hash_name == "sha256"
        return self.fingerprint


class FakeConnection:
    async def run(self, command: str, check: bool = False):
        assert command == "printf ASO_SSH_READY"
        assert check is False
        return SimpleNamespace(stdout="ASO_SSH_READY", stderr="", exit_status=0)


class FakeConnectionContext:
    def __init__(self, module: "FakeAsyncSsh", options: dict[str, object]) -> None:
        self.module = module
        self.options = options

    async def __aenter__(self):
        client_factory = self.options.get("client_factory")
        if client_factory is not None:
            client = client_factory()
            if not client.validate_host_public_key(
                str(self.options["host"]), str(self.options["host"]), int(self.options["port"]), self.module.presented_key
            ):
                raise ValueError(f"Host key is not trusted for host {self.options['host']}")
        return FakeConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAsyncSsh:
    class SSHClient:
        pass

    def __init__(self, *, stored: str, presented: str) -> None:
        self.stored_key = FakeKey(stored)
        self.presented_key = FakeKey(presented)
        self.connect_options: dict[str, object] | None = None

    def import_public_key(self, data: str):
        assert data.startswith("ssh-ed25519 ")
        return self.stored_key

    def connect(self, **options):
        self.connect_options = options
        return FakeConnectionContext(self, options)


@pytest.mark.asyncio
async def test_executor_enforces_explicitly_confirmed_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("172.239.4.64 ssh-ed25519 AAAATEST\n", encoding="utf-8")
    fake = FakeAsyncSsh(stored="SHA256:trusted", presented="SHA256:trusted")
    monkeypatch.setattr("app.deployment.ssh.importlib.import_module", lambda _: fake)

    result = await AsyncSshCommandExecutor().run(
        SshConnectionSpec(
            host="172.239.4.64",
            port=22,
            username="root",
            auth_method=SshAuthMethod.PASSWORD,
            secret=SecretStr("secret"),
            verify_host_key=True,
            known_hosts=str(known_hosts),
        ),
        "printf ASO_SSH_READY",
        timeout_seconds=2,
    )

    assert result.stdout == "ASO_SSH_READY"
    assert fake.connect_options is not None
    assert "client_factory" in fake.connect_options
    assert fake.connect_options["known_hosts"] == ((), (), (), (), (), (), ())
    assert fake.connect_options["config"] is None


@pytest.mark.asyncio
async def test_executor_rejects_changed_key_even_after_prior_trust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("172.239.4.64 ssh-ed25519 AAAATEST\n", encoding="utf-8")
    fake = FakeAsyncSsh(stored="SHA256:trusted", presented="SHA256:changed")
    monkeypatch.setattr("app.deployment.ssh.importlib.import_module", lambda _: fake)

    with pytest.raises(ValueError, match="Host key is not trusted"):
        await AsyncSshCommandExecutor().run(
            SshConnectionSpec(
                host="172.239.4.64",
                port=22,
                username="root",
                auth_method=SshAuthMethod.PASSWORD,
                secret=SecretStr("secret"),
                verify_host_key=True,
                known_hosts=str(known_hosts),
            ),
            "printf ASO_SSH_READY",
            timeout_seconds=2,
        )


def test_managed_known_hosts_pin_lookup_is_exact(tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        "172.239.4.64 ssh-ed25519 AAAAONE\n"
        "[172.239.4.64]:2222 ssh-ed25519 AAAATWO\n",
        encoding="utf-8",
    )
    fake = FakeAsyncSsh(stored="SHA256:trusted", presented="SHA256:trusted")

    assert load_trusted_host_key_fingerprint(
        str(known_hosts), "172.239.4.64", 22, asyncssh_module=fake
    ) == "SHA256:trusted"
    assert load_trusted_host_key_fingerprint(
        str(known_hosts), "172.239.4.64", 2222, asyncssh_module=fake
    ) == "SHA256:trusted"
    assert load_trusted_host_key_fingerprint(
        str(known_hosts), "172.239.4.65", 22, asyncssh_module=fake
    ) is None


def test_node_save_callback_recovers_untrusted_host_key() -> None:
    source = Path("app/bot/registry_ui.py").read_text(encoding="utf-8")
    save_branch = source[source.index('if data == "r.nac"'): source.index('if data.startswith("r.nsa.")')]
    assert "_is_untrusted_ssh_host_key_error" in save_branch
    assert 'resume_stage="node_confirm"' in save_branch
    assert "Retry Save Node" in source
