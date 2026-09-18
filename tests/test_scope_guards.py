from pathlib import Path


def test_all_seven_phases_are_present() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    assert (root / "providers" / "hetzner.py").exists()
    assert (root / "providers" / "linode.py").exists()
    assert (root / "deployment" / "service.py").exists()
    assert (root / "master" / "client.py").exists()
    assert (root / "replacement" / "orchestrator.py").exists()
    assert (root / "monitoring" / "check_host.py").exists()
    assert (root / "workers" / "monitoring.py").exists()
    assert (root / "workers" / "replacement.py").exists()

    # Phase 7 presentation/control and production composition.
    assert (root / "bot" / "application.py").exists()
    assert (root / "bot" / "callbacks.py").exists()
    assert (root / "control" / "service.py").exists()
    assert (root / "backup" / "manager.py").exists()
    assert (root / "workers" / "runner.py").exists()
    assert (root / "runtime.py").exists()


def test_telegram_business_logic_stays_out_of_handlers() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "bot" / "application.py"
    ).read_text(encoding="utf-8")
    assert "ProviderFactory(" not in source
    assert "NodeRepository(" not in source
    assert "ReplacementJobRepository(" not in source
    assert "CheckHostClient(" not in source
    assert "delete_server(" not in source
