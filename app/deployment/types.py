from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import SecretStr

from app.models.enums import SshAuthMethod


class PackageManager(StrEnum):
    APT = "apt"
    DNF = "dnf"
    YUM = "yum"
    APK = "apk"
    PACMAN = "pacman"
    ZYPPER = "zypper"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SshConnectionSpec:
    host: str
    port: int
    username: str
    auth_method: SshAuthMethod
    secret: SecretStr = field(repr=False)
    verify_host_key: bool = True
    known_hosts: str | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_status: int


@dataclass(frozen=True, slots=True)
class RemoteOsInfo:
    os_id: str
    version_id: str | None
    architecture: str
    package_manager: PackageManager


@dataclass(frozen=True, slots=True)
class ThreeXUiConfig:
    username: str
    password: SecretStr = field(repr=False)
    panel_port: int
    web_base_path: str
    access_url: str
    api_token: SecretStr = field(repr=False)
    db_type: str
