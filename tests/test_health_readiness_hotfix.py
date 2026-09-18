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
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.7-health-readiness-hotfix"
