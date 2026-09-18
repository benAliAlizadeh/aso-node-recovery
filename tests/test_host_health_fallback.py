from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_accepts_internal_docker_health_when_host_port_is_unreachable() -> None:
    source = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
    assert "Docker health is authoritative" in source
    assert "Continuing installation" in source
    assert "API is healthy inside Docker but the published host endpoint is unreachable" not in source


def test_asoctl_health_falls_back_to_internal_api() -> None:
    source = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    assert "curl --noproxy '*' --connect-timeout 1 --max-time 3" in source
    assert "checking the API inside Docker" in source
    assert "compose exec -T api python -c" in source
    assert "API health failed both from the host and inside Docker" in source


def test_release_version() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.5.3-safe-upgrade"
