from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import metadata  # noqa: E402
from app.models import NodeState  # noqa: E402
from app.services import NodeStateMachine  # noqa: E402

EXPECTED_TABLES = {"providers", "nodes", "node_credentials"}
RESERVED_PACKAGES = {"providers", "monitoring", "deployment", "workers", "bot"}


def main() -> int:
    assert set(metadata.tables) == EXPECTED_TABLES
    assert NodeStateMachine.can_transition(NodeState.UNKNOWN, NodeState.HEALTHY)
    assert not NodeStateMachine.can_transition(NodeState.UNKNOWN, NodeState.DEPLOYING)

    for package in RESERVED_PACKAGES:
        python_files = sorted((ROOT / "app" / package).glob("*.py"))
        assert [path.name for path in python_files] == ["__init__.py"]

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "0.2.0-phase2-registry-core"
    print("Patch 01 structural validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
