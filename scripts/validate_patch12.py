from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
installer = (ROOT / "scripts" / "quick_install.sh").read_text(encoding="utf-8")
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

assert version in {"1.0.7-health-readiness-hotfix", "1.1.0-smart-onboarding", "1.2.0-telegram-registry-ui", "1.3.0-api-health-center", "1.4.0-runtime-controls", "1.5.0-force-repair-hardening"}
assert "--noproxy '*'" in installer
assert "--connect-timeout 1" in installer
assert "--max-time 2" in installer
assert ".State.Health" in installer
assert "API container stopped before becoming healthy" in installer
assert "API container is restarting" in installer
assert "compose logs --tail=150 api" in installer
assert "after 60 seconds" in installer
print("Patch 12 health readiness validation: PASS")
