from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

MasterConnectionMode = Literal["auto", "remote", "local-host"]


@dataclass(frozen=True, slots=True)
class MasterRoute:
    base_url: str
    host_header: str | None
    label: str


def normalize_master_base_url(value: str) -> str:
    text = value.strip().rstrip("/")
    if not text:
        raise ValueError("master 3X-UI base URL cannot be blank")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("master 3X-UI base URL must use http or https")
    if not parsed.hostname:
        raise ValueError("master 3X-UI base URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("master 3X-UI base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("master 3X-UI base URL must not contain query/fragment components")
    return text


def derive_local_host_base_url(base_url: str) -> str:
    """Route the same scheme/port/base-path through Docker's host gateway.

    The configured/public Master URL remains the canonical identity. This helper only derives a
    transport endpoint for same-host Docker deployments.
    """

    canonical = normalize_master_base_url(base_url)
    parsed = urlsplit(canonical)
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"host.docker.internal{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", "")).rstrip("/")


def original_host_header(base_url: str) -> str:
    parsed = urlsplit(normalize_master_base_url(base_url))
    host = parsed.hostname or ""
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port is not None and parsed.port != default_port:
        return f"{host}:{parsed.port}"
    return host


def build_master_routes(
    base_url: str,
    *,
    mode: MasterConnectionMode,
    local_base_url: str | None = None,
) -> tuple[MasterRoute, ...]:
    canonical = normalize_master_base_url(base_url)
    local = normalize_master_base_url(local_base_url) if local_base_url else derive_local_host_base_url(canonical)
    remote_route = MasterRoute(base_url=canonical, host_header=None, label="remote")
    local_route = MasterRoute(
        base_url=local,
        host_header=original_host_header(canonical),
        label="local-host",
    )

    if mode == "remote":
        return (remote_route,)
    if mode == "local-host":
        return (local_route,)
    if mode == "auto":
        if remote_route.base_url == local_route.base_url:
            return (remote_route,)
        return (remote_route, local_route)
    raise ValueError(f"unsupported master connection mode: {mode}")
