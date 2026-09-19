from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

notifier = (ROOT / "app/bot/notifier.py").read_text(encoding="utf-8")
control = (ROOT / "app/control/service.py").read_text(encoding="utf-8")
monitoring = (ROOT / "app/workers/monitoring.py").read_text(encoding="utf-8")

checks = {
    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    == "1.5.8-node-event-notifications",
    "notifier resolves node context": "event_notification_context" in notifier,
    "node name is rendered": 'f"Node: {context.node_name}"' in notifier,
    "provider is rendered": 'f"Provider: {provider}"' in notifier,
    "VPS host is rendered": 'f"VPS IP/Host: {context.vps_host}"' in notifier,
    "state transition payload persisted": '"previous_state": result.previous_state.value' in monitoring,
    "event payload reaches snapshots": "payload=event.payload" in control,
    "no secret field is formatted": all(
        forbidden not in notifier
        for forbidden in ("api_token", "password_ref", "ssh_secret", "credential_ref")
    ),
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
if failed:
    raise SystemExit("validation failed: " + ", ".join(failed))
print("Patch 25 validation passed.")
