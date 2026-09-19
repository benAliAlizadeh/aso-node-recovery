from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

checks = {
    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.5.7-ssh-hostkey-probe-compat",
    "host-key probe uses AsyncSSH helper": "get_server_host_key" in (ROOT / "app/deployment/host_keys.py").read_text(encoding="utf-8"),
    "unsupported connect_timeout removed": "connect_timeout=self.timeout_seconds" not in (ROOT / "app/deployment/host_keys.py").read_text(encoding="utf-8"),
    "probe remains bounded": "asyncio.wait_for" in (ROOT / "app/deployment/host_keys.py").read_text(encoding="utf-8"),
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
if failed:
    raise SystemExit("validation failed: " + ", ".join(failed))
print("Patch 24 validation passed.")
