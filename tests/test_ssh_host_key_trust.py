from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.deployment.host_keys import AsyncSshHostKeyTrustService, SshHostKeyCandidate


class FakeKey:
    algorithm = b"ssh-ed25519"

    def __init__(self, fingerprint: str = "SHA256:trusted-fingerprint") -> None:
        self._fingerprint = fingerprint

    def get_fingerprint(self, hash_name: str = "sha256") -> str:
        assert hash_name == "sha256"
        return self._fingerprint

    def export_public_key(self, format_name: str = "openssh") -> bytes:
        assert format_name == "openssh"
        return b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFAKEKEY\n"


class FakeAsyncSsh:
    def __init__(self, key: FakeKey) -> None:
        self.key = key
        self.calls: list[tuple[str, int]] = []

    async def get_server_host_key(self, host: str, *, port: int, connect_timeout: float):
        self.calls.append((host, port))
        assert connect_timeout > 0
        return self.key


@pytest.mark.asyncio
async def test_host_key_probe_does_not_require_node_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeAsyncSsh(FakeKey())
    monkeypatch.setattr("app.deployment.host_keys.importlib.import_module", lambda _: fake)
    service = AsyncSshHostKeyTrustService(str(tmp_path / "known_hosts"), timeout_seconds=2)

    candidate = await service.inspect("172.239.4.64", 22)

    assert candidate.algorithm == "ssh-ed25519"
    assert candidate.fingerprint == "SHA256:trusted-fingerprint"
    assert candidate.known_hosts_entry.startswith("172.239.4.64 ssh-ed25519 ")
    assert fake.calls == [("172.239.4.64", 22)]
    assert not (tmp_path / "known_hosts").exists()


@pytest.mark.asyncio
async def test_trust_refetches_and_persists_exact_confirmed_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeAsyncSsh(FakeKey())
    monkeypatch.setattr("app.deployment.host_keys.importlib.import_module", lambda _: fake)
    path = tmp_path / "known_hosts"
    service = AsyncSshHostKeyTrustService(str(path), timeout_seconds=2)

    candidate = await service.trust(
        "172.239.4.64",
        2222,
        expected_fingerprint="SHA256:trusted-fingerprint",
    )

    assert candidate.fingerprint == "SHA256:trusted-fingerprint"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("[172.239.4.64]:2222 ssh-ed25519 ")
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_changed_fingerprint_is_never_auto_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeAsyncSsh(FakeKey("SHA256:new-key"))
    monkeypatch.setattr("app.deployment.host_keys.importlib.import_module", lambda _: fake)
    path = tmp_path / "known_hosts"
    service = AsyncSshHostKeyTrustService(str(path), timeout_seconds=2)

    with pytest.raises(Exception, match="changed before confirmation"):
        await service.trust(
            "172.239.4.64",
            22,
            expected_fingerprint="SHA256:old-key",
        )

    assert not path.exists()


def test_default_known_hosts_is_persistent_runtime_secret_file(tmp_path: Path) -> None:
    settings = Settings(environment="test", runtime_secret_dir=str(tmp_path))
    assert settings.effective_ssh_known_hosts_path == str(tmp_path / "known_hosts")


def test_telegram_onboarding_requires_explicit_fingerprint_confirmation() -> None:
    source = Path("app/bot/registry_ui.py").read_text(encoding="utf-8")
    assert "SSH host identity confirmation" in source
    assert "Trust this fingerprint" in source
    assert 'self.signer.encode("hk"' in source
    assert "trust_ssh_host_key" in source
    assert "ASO will keep strict SSH host-key verification enabled" in source


def test_cli_setup_previews_and_confirms_host_key_before_credentials() -> None:
    source = Path("scripts/asoctl.sh").read_text(encoding="utf-8")
    assert "ssh-host-key-preview" in source
    assert "ssh-host-key-trust" in source
    assert "Trust exactly this SSH fingerprint" in source
    assert source.index("trust_ssh_host_key_interactive") < source.index("SSH auth (private_key/password)")
