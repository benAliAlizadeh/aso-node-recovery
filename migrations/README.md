# Alembic migrations

Schema evolution is active from Patch 02 onward.

Current head:

```text
20260917_0001
```

Commands:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head --sql
```

Use the configured `ASO_DATABASE_URL` for online migrations. Do not place production credentials in
`alembic.ini`.
