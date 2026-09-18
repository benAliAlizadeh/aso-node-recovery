from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"[FAIL] {path}: missing {needle!r}")


def main() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != "1.4.0-runtime-controls":
        raise SystemExit(f"[FAIL] unexpected VERSION: {version}")

    require(
        "app/models/enums.py",
        "class NodeOperationMode",
        'AUTO_REPAIR = "auto_repair"',
        "class RuntimeExecutionMode",
    )
    require(
        "app/services/operational_settings.py",
        "RUNTIME_MONITORING_ENABLED_KEY",
        "RUNTIME_REPLACEMENT_ENABLED_KEY",
        "RUNTIME_EXECUTION_MODE_KEY",
        "live_capability",
        "effective_dry_run",
    )
    require(
        "app/workers/replacement.py",
        "list_auto_repair_failed",
        "effective_dry_run",
    )
    require(
        "app/bot/runtime_ui.py",
        "⚙️ Runtime Controls",
        "Monitor Only",
        "AUTO REPAIR",
        "Confirm LIVE",
    )
    require(
        "app/replacement/orchestrator.py",
        "is_dry_run=effective_dry_run",
        "get(provider, dry_run=job.is_dry_run)",
    )
    require(
        "migrations/versions/20260919_0005_node_operation_mode.py",
        "operation_mode",
        "monitor_only",
        "auto_repair",
    )

    # Telegram/runtime controls may select safer behavior but must never edit environment safety
    # switches or independently enable old-VPS deletion.
    ui = (ROOT / "app" / "bot" / "runtime_ui.py").read_text(encoding="utf-8")
    for forbidden in (
        "allow_old_vps_deletion = True",
        "allow_real_infrastructure_mutation = True",
        "settings.dry_run = False",
        ".delete_server(",
    ):
        if forbidden in ui:
            raise SystemExit(f"[FAIL] runtime UI contains forbidden safety bypass: {forbidden}")

    print("[PASS] Patch 16 monitoring/runtime control validation")


if __name__ == "__main__":
    main()
