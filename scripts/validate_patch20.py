from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if version != "1.5.3-safe-upgrade":
    raise SystemExit(f"unexpected VERSION: {version}")

required = [
    "scripts/asoctl.sh",
    "docs/UPGRADE.md",
    "tests/test_upgrade_workflow.py",
]
for relative in required:
    if not (ROOT / relative).exists():
        raise SystemExit(f"missing required file: {relative}")

ctl = (ROOT / "scripts/asoctl.sh").read_text(encoding="utf-8")
checks = {
    "upgrade command": "upgrade_stack()" in ctl and "  upgrade)" in ctl,
    "backup first": "pre-upgrade database backup" in ctl,
    "build": "compose build" in ctl,
    "migration": "compose run --rm api alembic upgrade head" in ctl,
    "recreate": "compose up -d --force-recreate api worker" in ctl,
    "health": '"$PROJECT_ROOT/asoctl" health' in ctl,
    "latest validator": "latest_validator()" in ctl and "sort -V | tail -n 1" in ctl,
    "file mode normalization": "core.fileMode false" in ctl,
    "no destructive volume removal": "down -v" not in ctl[ctl.index("upgrade_stack() {"):ctl.index("setup_registry() {")],
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("patch20 validation failed: " + ", ".join(failed))

print("Patch 20 validation: PASS")
