# 1.0.1 quick-installer release checklist

## Installation / packaging

- [ ] `sudo ./install.sh` or `sudo ./install.sh --non-interactive` completes on the target host
- [ ] `./asoctl health` reports the API healthy
- [ ] `./asoctl safety` confirms DRY_RUN is on and real mutation is off
- [ ] `.env` is mode 0600 and any pre-existing file was backed up before modification
- [ ] Docker Engine / Compose came from an approved existing installation or Docker's official apt repository

## Application verification

- [ ] `alembic upgrade head`
- [ ] full pytest suite passes
- [ ] Ruff check/format pass
- [ ] `scripts/validate_patch05.py` passes
- [ ] `scripts/validate_patch06.py` passes
- [ ] `scripts/security_review.py` passes against production environment
- [ ] Telegram allow-list and signed confirmations verified
- [ ] monitoring-only production soak completed
- [ ] backup created and validated
- [ ] isolated restore drill completed
- [ ] runtime-secret volume backup/restore procedure verified
- [ ] provider quotas/cost guards reviewed
- [ ] Master 3X-UI mapping reviewed (explicit IDs, never inferred by IP)
- [ ] SSH known-host trust material populated
- [ ] old-VPS protection test reviewed
- [ ] production E2E explicitly authorized before execution
- [ ] real infrastructure guards remain off until authorization

The quick installer only installs and safely boots the platform. It does not constitute authorization
for real provider mutation, Master changes, database restore, or a production replacement test.

- [ ] `scripts/validate_patch14.py` passes
