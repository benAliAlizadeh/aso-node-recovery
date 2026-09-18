from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"[FAIL] {path}: missing {needle!r}")


def main() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version not in {"1.3.0-api-health-center", "1.4.0-runtime-controls", "1.5.0-force-repair-hardening"}:
        raise SystemExit(f"[FAIL] unexpected VERSION: {version}")

    require(
        "app/diagnostics/service.py",
        "class ApiHealthService",
        "check_check_host",
        "check_master",
        "check_telegram",
        "check_providers",
        "check_nodes",
        'text("SELECT 1")',
        "probe_access()",
    )
    require(
        "app/bot/health_ui.py",
        "❤️ API Health Center",
        "🔄 Refresh All",
        "🧩 Core APIs",
        "☁️ Providers",
        "🖥 Node APIs",
        "Read-only diagnostics only",
    )
    require(
        "app/bot/application.py",
        'callback_data="m.health"',
        'CommandHandler("apihealth", self.api_health)',
        "self.health_ui.register(application)",
    )

    service = (ROOT / "app/diagnostics/service.py").read_text(encoding="utf-8")
    for forbidden in (
        ".create_server(",
        ".delete_server(",
        ".reboot_server(",
        ".update_node(",
        ".trigger_replacement(",
    ):
        if forbidden in service:
            raise SystemExit(f"[FAIL] API Health service contains destructive call {forbidden}")

    print("[PASS] Patch 15 API Health Center validation")


if __name__ == "__main__":
    main()
