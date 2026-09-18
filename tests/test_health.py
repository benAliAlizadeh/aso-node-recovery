from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_endpoint_reports_safe_defaults() -> None:
    settings = Settings(
        environment="test",
        dry_run=True,
        log_json=False,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "aso-node-recovery"
    assert body["environment"] == "test"
    assert body["dry_run"] is True
    assert body["version"] == "1.5.1-host-health-fallback"
