from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if version != "1.5.0-force-repair-hardening":
    raise SystemExit(f"unexpected VERSION: {version}")

required = [
    "app/replacement/orchestrator.py",
    "app/services/node_state.py",
    "app/bot/application.py",
    "app/bot/registry_ui.py",
    "migrations/versions/20260919_0006_force_repair.py",
    "docs/FORCE_REPAIR.md",
    "tests/test_force_repair.py",
]
for relative in required:
    if not (ROOT / relative).exists():
        raise SystemExit(f"missing required file: {relative}")

orchestrator = (ROOT / "app/replacement/orchestrator.py").read_text(encoding="utf-8")
bot = (ROOT / "app/bot/application.py").read_text(encoding="utf-8")
safety = (ROOT / "app/replacement/safety.py").read_text(encoding="utf-8")
model = (ROOT / "app/models/operations.py").read_text(encoding="utf-8")

checks = {
    "force admission": "force: bool = False" in orchestrator,
    "standard failure gate preserved": "replacement requires FAILED node" in orchestrator,
    "durable force metadata": "ReplacementTriggerMode.FORCE" in orchestrator and "request_key" in model,
    "pre-switch state restore": "restore_after_forced_replacement" in orchestrator,
    "signed force confirmation": 'self.signer.encode("fc"' in bot,
    "force request idempotency": "_force_request_key" in bot and "get_by_request_key" in orchestrator,
    "final health gate preserved": "ReplacementCheckpoint.FINAL_CHECK" in orchestrator,
    "old-vps deletion gate preserved": "allow_old_vps_deletion" in orchestrator,
    "old-vps final verification guard": "final_health_verified" in safety,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("patch17 validation failed: " + ", ".join(failed))

print("Patch 17 validation: PASS")
