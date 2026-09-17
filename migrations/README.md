# Migrations

Patch 01 defines the first SQLAlchemy registry metadata, but intentionally does **not** create or apply
an Alembic migration yet. Patch 02 owns Alembic initialization and the first migration after the
remaining Phase 2 models/constraints are present, avoiding an unnecessary intermediate production
schema revision during initial development.
