from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "master_host_firewall.sh"


def test_remote_master_mode_never_touches_firewall(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    (project / ".env").write_text(
        "ASO_MASTER_3XUI_BASE_URL=https://master.example.test:2053/QAZ\n"
        "ASO_MASTER_3XUI_CONNECTION_MODE=remote\n",
        encoding="utf-8",
    )
    (project / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")

    marker = tmp_path / "ufw-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ufw = fake_bin / "ufw"
    ufw.write_text(f"#!/bin/sh\necho called > {marker}\nexit 99\n", encoding="utf-8")
    ufw.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(scripts / SCRIPT.name), "--apply"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "remote" in result.stdout.lower()
    assert not marker.exists()


def test_guard_rule_is_narrow_bridge_subnet_and_port_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'ufw insert 1 allow in on "$bridge" from "$subnet" to any port "$MASTER_PORT" proto tcp' in source
    for forbidden in ("ufw reset", "ufw disable", "ufw delete", "iptables -F"):
        assert forbidden not in source


def test_guard_discovers_runtime_network_and_reverifies_connectivity() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "compose ps -q api" in source
    assert ".NetworkSettings.Networks" in source
    assert "docker network inspect" in source
    assert 'bridge="br-${network_id:0:12}"' in source
    assert source.count('container_can_reach_host_master "$MASTER_PORT"') >= 2
    assert "host.docker.internal" in source


def test_quick_installer_runs_guard_after_api_health() -> None:
    source = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
    install = source[source.index("install_stack() {"):source.index("print_summary() {")]
    assert install.index("wait_for_health") < install.index('scripts/master_host_firewall.sh" --apply')
    assert "Installation will continue" in install


def test_asoctl_exposes_guard_and_upgrade_invokes_it() -> None:
    source = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    assert "master_network_check()" in source
    assert "master-network-check)" in source
    upgrade = source[source.index("upgrade_stack() {"):source.index("setup_registry() {")]
    assert "same-server Master network guard" in upgrade
    assert "master_network_check" in upgrade


def test_release_version() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.5.5-upgrade-validator-ssh-trust"


def test_same_server_guard_applies_only_narrow_rule_and_rechecks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    (project / ".env").write_text(
        "ASO_MASTER_3XUI_BASE_URL=http://master.local.test:2053/QAZ\n"
        "ASO_MASTER_3XUI_CONNECTION_MODE=auto\n",
        encoding="utf-8",
    )
    (project / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "ufw-applied"
    args_file = tmp_path / "ufw-args"

    (fake_bin / "docker").write_text(
        "#!/bin/sh\n"
        f"MARKER='{marker}'\n"
        "if [ \"$1\" = compose ]; then\n"
        "  shift\n"
        "  while [ $# -gt 0 ]; do case \"$1\" in --env-file|-f) shift 2 ;; *) break ;; esac; done\n"
        "  if [ \"$1\" = ps ] && [ \"$2\" = -q ] && [ \"$3\" = api ]; then echo cid123; exit 0; fi\n"
        "  if [ \"$1\" = exec ]; then [ -f \"$MARKER\" ] && exit 0 || exit 1; fi\n"
        "fi\n"
        "if [ \"$1\" = inspect ]; then echo aso-node-recovery_default; exit 0; fi\n"
        "if [ \"$1\" = network ] && [ \"$2\" = inspect ]; then\n"
        "  echo \"$*\" | grep -q '{{.Id}}' && echo 38788fe5528cabcdef || echo 172.19.0.0/16\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    (fake_bin / "getent").write_text(
        "#!/bin/sh\necho '91.99.226.142 STREAM master.local.test'\n", encoding="utf-8"
    )
    (fake_bin / "ip").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = -4 ]; then echo '2: eth0 inet 91.99.226.142/32 brd 91.99.226.142 scope global eth0'; exit 0; fi\n"
        "if [ \"$1\" = link ] && [ \"$2\" = show ] && [ \"$3\" = br-38788fe5528c ]; then exit 0; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "ss").write_text("#!/bin/sh\necho 'LISTEN 0 4096 *:2053 *:*'\n", encoding="utf-8")
    (fake_bin / "ufw").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = status ]; then echo 'Status: active'; exit 0; fi\n"
        f"if [ \"$1\" = insert ]; then echo \"$*\" > '{args_file}'; touch '{marker}'; exit 0; fi\n"
        "if [ \"$1\" = reload ]; then exit 0; fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    (fake_bin / "sudo").write_text("#!/bin/sh\nexec \"$@\"\n", encoding="utf-8")
    for command in ("docker", "getent", "ip", "ss", "ufw", "sudo"):
        (fake_bin / command).chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(scripts / SCRIPT.name), "--apply"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Verified Docker -> local 3X-UI Master" in result.stdout
    rule = args_file.read_text(encoding="utf-8")
    assert "insert 1 allow in on br-38788fe5528c" in rule
    assert "from 172.19.0.0/16" in rule
    assert "port 2053 proto tcp" in rule
