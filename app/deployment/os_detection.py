from __future__ import annotations

import shlex

from app.core.errors import ConfigurationError
from app.deployment.ssh import RemoteCommandExecutor
from app.deployment.types import PackageManager, RemoteOsInfo, SshConnectionSpec


class RemoteOsDetector:
    _COMMAND = """set -eu
if [ -r /etc/os-release ]; then . /etc/os-release; elif [ -r /usr/lib/os-release ]; then . /usr/lib/os-release; else exit 44; fi
printf 'ID=%s\\nVERSION_ID=%s\\nARCH=%s\\n' \"${ID:-unknown}\" \"${VERSION_ID:-}\" \"$(uname -m)\"
"""

    def __init__(self, executor: RemoteCommandExecutor) -> None:
        self.executor = executor

    async def detect(self, spec: SshConnectionSpec) -> RemoteOsInfo:
        result = await self.executor.run(spec, self._COMMAND, timeout_seconds=20.0)
        if result.exit_status != 0:
            raise ConfigurationError("remote operating system could not be detected")
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
        os_id = values.get("ID", "unknown").lower()
        return RemoteOsInfo(
            os_id=os_id,
            version_id=values.get("VERSION_ID") or None,
            architecture=values.get("ARCH", "unknown"),
            package_manager=self._package_manager(os_id),
        )

    @staticmethod
    def _package_manager(os_id: str) -> PackageManager:
        if os_id in {"ubuntu", "debian", "armbian"}:
            return PackageManager.APT
        if os_id in {"fedora", "rhel", "rocky", "almalinux", "ol", "amzn", "centos"}:
            return PackageManager.DNF
        if os_id == "alpine":
            return PackageManager.APK
        if os_id in {"arch", "manjaro", "parch"}:
            return PackageManager.PACMAN
        if os_id in {"opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
            return PackageManager.ZYPPER
        return PackageManager.UNKNOWN


class RemoteBootstrapper:
    def __init__(self, executor: RemoteCommandExecutor) -> None:
        self.executor = executor

    async def bootstrap(self, spec: SshConnectionSpec, os_info: RemoteOsInfo) -> None:
        commands = {
            PackageManager.APT: (
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -y && apt-get install -y curl ca-certificates"
            ),
            PackageManager.DNF: "dnf install -y curl ca-certificates || yum install -y curl ca-certificates",
            PackageManager.YUM: "yum install -y curl ca-certificates",
            PackageManager.APK: "apk add --no-cache curl ca-certificates",
            PackageManager.PACMAN: "pacman -Sy --noconfirm curl ca-certificates",
            PackageManager.ZYPPER: "zypper --non-interactive install curl ca-certificates",
        }
        command = commands.get(os_info.package_manager)
        if command is None:
            raise ConfigurationError(
                f"unsupported remote OS for bootstrap: {shlex.quote(os_info.os_id)}"
            )
        result = await self.executor.run(spec, command, timeout_seconds=180.0)
        if result.exit_status != 0:
            raise RuntimeError("remote bootstrap failed")
