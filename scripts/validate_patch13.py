from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"{path}: missing required marker: {needle}")


def main() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version not in {"1.1.0-smart-onboarding", "1.2.0-telegram-registry-ui", "1.3.0-api-health-center", "1.4.0-runtime-controls"}:
        raise SystemExit(f"unexpected VERSION: {version}")

    require(
        "app/registry/discovery.py",
        "class SmartOnboardingDiscoveryService",
        "await adapter.probe_access()",
        "await adapter.get_server(provider_server_id)",
        "await master_client.get_node(master_node_id)",
        "await master_client.probe_node(master_node_id)",
        "verify_access_url",
    )
    require(
        "scripts/asoctl.sh",
        "smart-add-provider",
        "smart-preview-node",
        "smart-add-node",
        "candidate-",
        "Automatic replacement remains disabled.",
    )
    require(
        "app/registry/service.py",
        "provider_host",
        "provider.default_image",
        "host=provider_host",
        "image=(provider_image",
    )
    require("docs/SMART_ONBOARDING.md", "read-only against cloud providers", "./asoctl setup", "stored per current VPS/Node")

    require("migrations/versions/20260919_0004_smart_onboarding_vps_image.py", "op.add_column", "image")

    onboarding = (ROOT / "app/registry/discovery.py").read_text(encoding="utf-8")
    forbidden = ("create_server(", "delete_server(", "reboot_server(", "update_node(")
    for marker in forbidden:
        if marker in onboarding:
            raise SystemExit(f"smart discovery unexpectedly contains destructive marker: {marker}")

    print("Patch 13 smart onboarding validation passed.")


if __name__ == "__main__":
    main()
