from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models  # noqa: E402,F401
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.database import metadata  # noqa: E402
from app.monitoring.check_host import CheckHostClient  # noqa: E402
from app.monitoring.health import ReachabilityEvaluator  # noqa: E402
from app.monitoring.types import CheckHostRequest, ReachabilityDecision  # noqa: E402

EXPECTED_TABLES = {
    "providers",
    "nodes",
    "node_credentials",
    "node_checks",
    "vps_instances",
    "replacement_jobs",
    "deployments",
    "events",
    "settings",
}


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "0.3.0-registry-monitoring"

    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.check_host_country_code == "ir"
    assert settings.failure_threshold > 1
    assert settings.recovery_threshold > 1
    assert settings.monitoring_scheduler_enabled is False

    assert set(metadata.tables) == EXPECTED_TABLES
    dialect = postgresql.dialect()
    for table in metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))

    request = CheckHostRequest(
        request_id="validation",
        permanent_link=None,
        nodes=("ir1", "ir2", "ir3"),
        target="203.0.113.10:443",
    )
    summary = CheckHostClient.parse_tcp_result(
        request,
        {
            "ir1": [{"time": 0.01, "address": "203.0.113.10"}],
            "ir2": [{"time": 0.02, "address": "203.0.113.10"}],
            "ir3": [{"time": 0.03, "address": "203.0.113.10"}],
        },
    )
    assert (
        ReachabilityEvaluator.evaluate(summary, min_success_nodes=3)
        is ReachabilityDecision.REACHABLE
    )

    migration = ROOT / "migrations" / "versions" / "20260917_0001_registry_and_monitoring.py"
    assert migration.exists()

    print("Patch 02 validation: PASS")
    print(f"Version: {version}")
    print(f"Tables: {len(EXPECTED_TABLES)}")
    print("Safety: DRY_RUN defaults true; scheduler defaults disabled")
    print("Monitoring: Iran-scoped discovery + 3-node success quorum validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
