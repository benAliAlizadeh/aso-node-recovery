from pathlib import Path


def test_phase4_and_phase5_packages_are_implemented_but_master_and_bot_are_deferred() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    assert (root / "providers" / "hetzner.py").exists()
    assert (root / "providers" / "linode.py").exists()
    assert (root / "providers" / "provisioning.py").exists()
    assert (root / "deployment" / "ssh.py").exists()
    assert (root / "deployment" / "installer.py").exists()
    assert (root / "deployment" / "service.py").exists()

    # Telegram remains Phase 7. Master mutation/replacement orchestration remains Phase 6.
    assert sorted(path.name for path in (root / "bot").glob("*.py")) == ["__init__.py"]
    assert not (root / "services" / "replacement.py").exists()
    assert not (root / "services" / "master_3xui.py").exists()


def test_monitoring_packages_remain_implemented() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    assert (root / "monitoring" / "check_host.py").exists()
    assert (root / "monitoring" / "health.py").exists()
    assert (root / "monitoring" / "scheduler.py").exists()
    assert (root / "workers" / "monitoring.py").exists()
