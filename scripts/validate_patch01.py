from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import metadata  # noqa: E402
from app.models import NodeState  # noqa: E402
from app.services import NodeStateMachine  # noqa: E402

CORE_TABLES = {"providers", "nodes", "node_credentials"}


def main() -> int:
    assert CORE_TABLES.issubset(metadata.tables)
    assert NodeStateMachine.can_transition(NodeState.UNKNOWN, NodeState.HEALTHY)
    assert not NodeStateMachine.can_transition(NodeState.UNKNOWN, NodeState.DEPLOYING)

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version == "0.2.0-phase2-registry-core":
        reserved_packages = {"providers", "monitoring", "deployment", "workers", "bot"}
        for package in reserved_packages:
            python_files = sorted((ROOT / "app" / package).glob("*.py"))
            assert [path.name for path in python_files] == ["__init__.py"]

    print("Patch 01 invariants validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
