from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if version != "1.5.5-upgrade-validator-ssh-trust":
    raise SystemExit(f"unexpected VERSION: {version}")

ctl = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
ui = (ROOT / "app" / "bot" / "registry_ui.py").read_text(encoding="utf-8")
checks = {
    "source-mounted release validator": '-v "$PROJECT_ROOT:/source:ro"' in ctl and 'python "/source/scripts/${validator}"' in ctl,
    "production image remains test-free": not (ROOT / "docker" / "prod.Dockerfile").read_text(encoding="utf-8").find("COPY tests") >= 0,
    "host-key fallback helper": "_is_untrusted_ssh_host_key_error" in ui,
    "add-node fallback": 'resume_stage="node_ssh_secret"' in ui,
    "edit-ssh fallback": 'resume_stage="node_ssh_edit_secret"' in ui,
    "strict trust flow retained": "Trust this fingerprint" in ui,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("patch22 validation failed: " + ", ".join(failed))
print("Patch 22 upgrade validator + SSH trust fallback validation: PASS")
