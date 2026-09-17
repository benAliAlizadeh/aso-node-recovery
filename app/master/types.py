from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class MasterNode:
    id: int
    name: str
    remark: str
    scheme: str
    address: str
    port: int
    base_path: str
    has_api_token: bool
    enable: bool
    allow_private_address: bool
    tls_verify_mode: str
    pinned_cert_sha256: str
    inbound_sync_mode: str
    inbound_tags: tuple[str, ...]
    outbound_tag: str
    guid: str
    status: str
    xray_state: str
    transitive: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MasterNode:
        return cls(
            id=int(payload["id"]),
            name=str(payload.get("name") or ""),
            remark=str(payload.get("remark") or ""),
            scheme=str(payload.get("scheme") or "http"),
            address=str(payload.get("address") or ""),
            port=int(payload.get("port") or 0),
            base_path=str(payload.get("basePath") or ""),
            has_api_token=bool(payload.get("hasApiToken")),
            enable=bool(payload.get("enable", True)),
            allow_private_address=bool(payload.get("allowPrivateAddress", False)),
            tls_verify_mode=str(payload.get("tlsVerifyMode") or "verify"),
            pinned_cert_sha256=str(payload.get("pinnedCertSha256") or ""),
            inbound_sync_mode=str(payload.get("inboundSyncMode") or "all"),
            inbound_tags=tuple(str(item) for item in (payload.get("inboundTags") or [])),
            outbound_tag=str(payload.get("outboundTag") or ""),
            guid=str(payload.get("guid") or ""),
            status=str(payload.get("status") or ""),
            xray_state=str(payload.get("xrayState") or ""),
            transitive=bool(payload.get("transitive", False)),
            raw={
                str(key): value
                for key, value in payload.items()
                if str(key).lower() not in {"apitoken", "password", "token"}
            },
        )

    def safe_snapshot(self) -> dict[str, Any]:
        """Persist rollback metadata without any credential material."""
        return {
            "id": self.id,
            "name": self.name,
            "remark": self.remark,
            "scheme": self.scheme,
            "address": self.address,
            "port": self.port,
            "basePath": self.base_path,
            "hasApiToken": self.has_api_token,
            "enable": self.enable,
            "allowPrivateAddress": self.allow_private_address,
            "tlsVerifyMode": self.tls_verify_mode,
            "pinnedCertSha256": self.pinned_cert_sha256,
            "inboundSyncMode": self.inbound_sync_mode,
            "inboundTags": list(self.inbound_tags),
            "outboundTag": self.outbound_tag,
            "guid": self.guid,
            "status": self.status,
            "xrayState": self.xray_state,
            "transitive": self.transitive,
        }


@dataclass(frozen=True, slots=True)
class MasterNodeMutation:
    name: str
    remark: str
    scheme: str
    address: str
    port: int
    base_path: str
    api_token: SecretStr | None = field(default=None, repr=False)
    clear_api_token: bool = False
    enable: bool = True
    allow_private_address: bool = False
    tls_verify_mode: str = "verify"
    pinned_cert_sha256: str = ""
    inbound_sync_mode: str = "all"
    inbound_tags: tuple[str, ...] = ()
    outbound_tag: str = ""

    @classmethod
    def from_existing(
        cls,
        existing: MasterNode,
        *,
        scheme: str,
        address: str,
        port: int,
        base_path: str,
        api_token: SecretStr | None,
    ) -> MasterNodeMutation:
        if existing.transitive:
            raise ValueError("transitive 3X-UI nodes are read-only and cannot be replaced")
        tls_mode = existing.tls_verify_mode
        pinned = existing.pinned_cert_sha256
        if scheme != "https":
            tls_mode = "verify"
            pinned = ""
        return cls(
            name=existing.name,
            remark=existing.remark,
            scheme=scheme,
            address=address,
            port=port,
            base_path=base_path,
            api_token=api_token,
            enable=existing.enable,
            allow_private_address=existing.allow_private_address,
            tls_verify_mode=tls_mode,
            pinned_cert_sha256=pinned,
            inbound_sync_mode=existing.inbound_sync_mode,
            inbound_tags=existing.inbound_tags,
            outbound_tag=existing.outbound_tag,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
        *,
        api_token: SecretStr | None,
    ) -> MasterNodeMutation:
        return cls(
            name=str(snapshot.get("name") or ""),
            remark=str(snapshot.get("remark") or ""),
            scheme=str(snapshot.get("scheme") or "http"),
            address=str(snapshot.get("address") or ""),
            port=int(snapshot.get("port") or 0),
            base_path=str(snapshot.get("basePath") or ""),
            api_token=api_token,
            enable=bool(snapshot.get("enable", True)),
            allow_private_address=bool(snapshot.get("allowPrivateAddress", False)),
            tls_verify_mode=str(snapshot.get("tlsVerifyMode") or "verify"),
            pinned_cert_sha256=str(snapshot.get("pinnedCertSha256") or ""),
            inbound_sync_mode=str(snapshot.get("inboundSyncMode") or "all"),
            inbound_tags=tuple(str(item) for item in (snapshot.get("inboundTags") or [])),
            outbound_tag=str(snapshot.get("outboundTag") or ""),
        )

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "remark": self.remark,
            "scheme": self.scheme,
            "address": self.address,
            "port": self.port,
            "basePath": self.base_path,
            "enable": self.enable,
            "allowPrivateAddress": self.allow_private_address,
            "tlsVerifyMode": self.tls_verify_mode,
            "pinnedCertSha256": self.pinned_cert_sha256,
            "inboundSyncMode": self.inbound_sync_mode,
            "inboundTags": list(self.inbound_tags),
            "outboundTag": self.outbound_tag,
        }
        if self.api_token is not None:
            payload["apiToken"] = self.api_token.get_secret_value()
        if self.clear_api_token:
            payload["clearApiToken"] = True
        return payload
