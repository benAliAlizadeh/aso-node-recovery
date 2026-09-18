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
    if version not in {"1.2.0-telegram-registry-ui", "1.3.0-api-health-center", "1.4.0-runtime-controls"}:
        raise SystemExit(f"[FAIL] unexpected VERSION: {version}")

    require(
        "app/bot/registry_ui.py",
        "➕ Add Provider",
        "➕ Add Node",
        "Replace API Token",
        "Test All Access",
        "Remove from ASO",
        "MessageHandler",
        "filters.TEXT & ~filters.COMMAND",
    )
    require(
        "app/registry/management.py",
        "validate_provider_token",
        "discover_node",
        "validate_node_api_token",
        "validate_ssh",
        "replace_provider_token",
        "replace_node_api_token",
        "replace_node_ssh",
        "remove_node_from_registry",
    )
    require(
        "app/bot/application.py",
        "TelegramRegistryController",
        "self.registry_ui.register(application)",
        "self.registry_ui.render_nodes",
        "self.registry_ui.render_providers",
    )

    management = (ROOT / "app/registry/management.py").read_text(encoding="utf-8")
    for forbidden in (".create_server(", ".delete_server(", ".reboot_server(", ".update_node("):
        if forbidden in management:
            raise SystemExit(f"[FAIL] registry management contains destructive call {forbidden}")

    print("[PASS] Patch 14 Telegram registry management validation")


if __name__ == "__main__":
    main()
