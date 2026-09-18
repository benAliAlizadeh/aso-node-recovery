# 1.0.0 production release checklist

- [ ] `alembic upgrade head`
- [ ] full pytest suite passes
- [ ] Ruff check/format pass
- [ ] `scripts/validate_patch05.py` passes
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
