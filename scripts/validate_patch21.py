from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if version != "1.5.4-network-ssh-trust":
    raise SystemExit(f"unexpected VERSION: {version}")

required = [
    "scripts/master_host_firewall.sh",
    "scripts/quick_install.sh",
    "scripts/asoctl.sh",
    "tests/test_master_firewall_guard.py",
    "app/deployment/host_keys.py",
    "tests/test_ssh_host_key_trust.py",
]
for relative in required:
    if not (ROOT / relative).exists():
        raise SystemExit(f"missing required file: {relative}")

guard = (ROOT / "scripts" / "master_host_firewall.sh").read_text(encoding="utf-8")
installer = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
ctl = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
checks = {
    "remote untouched": "connection mode is remote; host firewall is intentionally untouched" in guard,
    "auto local detection": "host_resolves_local" in guard,
    "actual Docker subnet": ".NetworkSettings.Networks" in guard and "docker network inspect" in guard,
    "narrow UFW insert": 'ufw insert 1 allow in on "$bridge" from "$subnet" to any port "$MASTER_PORT" proto tcp' in guard,
    "no firewall deletion": "ufw delete" not in guard and "ufw reset" not in guard and "iptables -F" not in guard,
    "post-rule verification": guard.count('container_can_reach_host_master "$MASTER_PORT"') >= 2,
    "installer integration": 'scripts/master_host_firewall.sh" --apply' in installer,
    "asoctl command": "master-network-check)" in ctl,
    "upgrade integration": "same-server Master network guard" in ctl,
    "idempotent UFW": "no duplicate rule added" in guard,
}

host_keys = (ROOT / "app" / "deployment" / "host_keys.py").read_text(encoding="utf-8")
registry_ui = (ROOT / "app" / "bot" / "registry_ui.py").read_text(encoding="utf-8")
registry_cli = (ROOT / "scripts" / "registry_cli.py").read_text(encoding="utf-8")
ssh_checks = {
    "host key read-only probe": "get_server_host_key" in host_keys,
    "explicit fingerprint match": "expected_fingerprint" in host_keys and "changed before confirmation" in host_keys,
    "persistent known_hosts": "known_hosts_entry" in host_keys and "os.replace" in host_keys,
    "telegram confirmation": "SSH host identity confirmation" in registry_ui and 'self.signer.encode("hk"' in registry_ui,
    "CLI confirmation": "ssh-host-key-preview" in registry_cli and "ssh-host-key-trust" in registry_cli,
    "strict verification retained": "ASO will keep strict SSH host-key verification enabled" in registry_ui,
}
checks.update(ssh_checks)
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("patch21 validation failed: " + ", ".join(failed))
print("Patch 21 Master firewall + SSH host trust validation: PASS")
