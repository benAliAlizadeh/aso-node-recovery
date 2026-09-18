# Backup and restore

Database backups use PostgreSQL custom-format archives (`pg_dump -Fc`). Every created archive is
immediately validated with `pg_restore --list` before it is considered successful.

```bash
python scripts/backup_db.py
```

Backup files are owner-only and old archives are pruned according to
`ASO_BACKUP_RETENTION_COUNT`.

## Restore

Restore is destructive and has two independent gates:

```env
ASO_ALLOW_DATABASE_RESTORE=true
```

and the explicit confirmation phrase:

```bash
python scripts/restore_db.py /var/lib/aso/backups/aso-....dump \
  --confirm RESTORE_ASO_DATABASE
```

The restore command validates the archive first and uses `--clean --if-exists --exit-on-error`.

## Restore test

A restore drill must target a separate, empty database. `DatabaseBackupManager.restore_test()` refuses
to use the configured production database name.

## Runtime secrets

Generated 3X-UI API tokens/passwords are stored under `ASO_RUNTIME_SECRET_DIR`, outside PostgreSQL.
A database backup alone is therefore not a complete disaster-recovery backup. In production, back up
the runtime-secret volume with an encrypted/controlled secret-storage process and test restoring it
together with PostgreSQL.
