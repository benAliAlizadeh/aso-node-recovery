from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if version != "1.5.2-master-auto-routing":
    raise SystemExit(f"unexpected VERSION: {version}")

required = [
    "app/master/routing.py",
    "app/master/client.py",
    "app/master/factory.py",
    "tests/test_master_auto_routing.py",
    "docs/MASTER_3XUI.md",
]
for relative in required:
    if not (ROOT / relative).exists():
        raise SystemExit(f"missing required file: {relative}")

config = (ROOT / "app/core/config.py").read_text(encoding="utf-8")
client = (ROOT / "app/master/client.py").read_text(encoding="utf-8")
routing = (ROOT / "app/master/routing.py").read_text(encoding="utf-8")
factory = (ROOT / "app/master/factory.py").read_text(encoding="utf-8")
compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
diagnostics = (ROOT / "app/diagnostics/service.py").read_text(encoding="utf-8")

checks = {
    "auto mode config": 'Literal["auto", "remote", "local-host"] = "auto"' in config,
    "optional local override": "master_3xui_local_base_url" in config,
    "docker host gateway": '"host.docker.internal:host-gateway"' in compose,
    "remote first route": 'return (remote_route, local_route)' in routing,
    "network-only fallback": 'except (httpx.TimeoutException, httpx.NetworkError)' in client,
    "auth stays authoritative": 'response.status_code in {401, 403}' in client,
    "tcp auto probe": "_probe_tcp_route" in client and "asyncio.open_connection" in client,
    "local read-only verification": "_verify_local_authenticated_route" in client and "/panel/api/nodes/list" in client,
    "factory uses connection mode": "master_3xui_connection_mode" in factory,
    "health shows route": "authenticated via {route}" in diagnostics,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("patch19 validation failed: " + ", ".join(failed))

print("Patch 19 validation: PASS")
