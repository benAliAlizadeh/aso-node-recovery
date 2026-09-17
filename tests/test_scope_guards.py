from pathlib import Path


def test_patch02_keeps_future_external_integrations_deferred() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    # Provider APIs, deployment/SSH, Telegram, and master mutation are later patches.
    reserved_packages = ["providers", "deployment", "bot"]
    for package in reserved_packages:
        python_files = sorted((root / package).glob("*.py"))
        assert [path.name for path in python_files] == ["__init__.py"]


def test_monitoring_and_worker_packages_are_now_implemented() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    assert (root / "monitoring" / "check_host.py").exists()
    assert (root / "monitoring" / "health.py").exists()
    assert (root / "monitoring" / "scheduler.py").exists()
    assert (root / "workers" / "monitoring.py").exists()
