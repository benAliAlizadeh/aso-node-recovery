from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if version != "1.5.6-ssh-pinned-trust":
    raise SystemExit(f"unexpected VERSION: {version}")

ssh = (ROOT / "app" / "deployment" / "ssh.py").read_text(encoding="utf-8")
host_keys = (ROOT / "app" / "deployment" / "host_keys.py").read_text(encoding="utf-8")
ui = (ROOT / "app" / "bot" / "registry_ui.py").read_text(encoding="utf-8")
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

checks = {
    "managed fingerprint loader": "load_trusted_host_key_fingerprint" in host_keys,
    "host-key probe ignores ambient ssh config": "config=None" in host_keys,
    "runtime fingerprint pinning": "hmac.compare_digest" in ssh and "client_factory" in ssh,
    "strict verification retained": 'options["known_hosts"] = None' in ssh,
    "final-save trust recovery": 'resume_stage="node_confirm"' in ui and "Retry Save Node" in ui,
    "current asyncssh floor": 'asyncssh>=2.24.0,<3' in pyproject,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("patch23 validation failed: " + ", ".join(failed))
print("Patch 23 SSH pinned trust + save recovery validation: PASS")
