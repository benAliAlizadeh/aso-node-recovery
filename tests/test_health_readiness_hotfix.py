from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_health_wait_is_bounded_and_proxy_safe() -> None:
    source = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
    assert "curl --noproxy '*' --connect-timeout 1 --max-time 2" in source
    assert "docker inspect -f '{{.State.Status}}'" in source
    assert ".State.Health" in source
    assert "compose logs --tail=150 api" in source
    assert "API did not become healthy at $url after 60 seconds" in source


def test_release_version() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() in {"1.0.7-health-readiness-hotfix", "1.1.0-smart-onboarding", "1.2.0-telegram-registry-ui", "1.3.0-api-health-center", "1.4.0-runtime-controls", "1.5.0-force-repair-hardening", "1.5.1-host-health-fallback", "1.5.2-master-auto-routing", "1.5.3-safe-upgrade", "1.5.4-master-firewall-guard", "1.5.4-network-ssh-trust"}
