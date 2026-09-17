from pathlib import Path


def test_phases4_to6_are_implemented_but_telegram_is_deferred() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    assert (root / "providers" / "hetzner.py").exists()
    assert (root / "providers" / "linode.py").exists()
    assert (root / "providers" / "provisioning.py").exists()
    assert (root / "deployment" / "ssh.py").exists()
    assert (root / "deployment" / "installer.py").exists()
    assert (root / "deployment" / "service.py").exists()

    assert (root / "master" / "client.py").exists()
    assert (root / "replacement" / "orchestrator.py").exists()
    assert (root / "workers" / "replacement.py").exists()

    # Telegram remains Phase 7 and must not contain business logic yet.
    assert sorted(path.name for path in (root / "bot").glob("*.py")) == ["__init__.py"]


def test_monitoring_packages_remain_implemented() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    assert (root / "monitoring" / "check_host.py").exists()
    assert (root / "monitoring" / "health.py").exists()
    assert (root / "monitoring" / "scheduler.py").exists()
    assert (root / "workers" / "monitoring.py").exists()
