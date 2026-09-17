# Development Rules

- Inspect before modifying an existing module.
- Search before creating a duplicate class/function.
- Keep external-service details behind adapters.
- Keep persistence access out of transport handlers.
- Never hard-code credentials.
- Never log tokens, passwords, private keys, Authorization headers, or cookies.
- `DRY_RUN` must remain true by default.
- Real destructive infrastructure tests require explicit authorization and must be separately marked.
- Schema changes beginning in Phase 2 require Alembic migrations.
- Each large delivery must keep tests and lint clean before the next delivery.
