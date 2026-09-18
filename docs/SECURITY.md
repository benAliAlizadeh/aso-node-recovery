# Security controls

- `DRY_RUN=true`, `ALLOW_REAL_INFRASTRUCTURE_MUTATION=false`, and `ALLOW_OLD_VPS_DELETION=false` are independent safe defaults.
- Production configuration refuses disabled SSH host-key verification or disabled TLS verification
  for node/master 3X-UI.
- Telegram access is an explicit user-ID allow-list.
- Destructive Telegram confirmations are user-bound, HMAC signed, and expire.
- Provider credentials, Master credentials, Telegram token, SSH secrets, and generated 3X-UI tokens
  are never stored as plaintext audit payloads.
- Provider credentials are secret references; generated node secrets are owner-only files.
- The old VPS deletion path remains protected by the Phase 6 durable verification gates, a separate old-VPS deletion switch, an exact confirmation phrase, registry identity checks, and a provider read-back IP check immediately before deletion.
- Docker production application containers run non-root, drop Linux capabilities, use
  `no-new-privileges`, read-only root filesystems, bounded PIDs/CPU/memory, and log rotation.
- PostgreSQL is not published to the host in the production Compose file.
- Database restore has an independent disabled-by-default gate and confirmation phrase.

Run:

```bash
python scripts/security_review.py
```

before changing either real-infrastructure guard.

## Old VPS deletion hard gate

Real provisioning can be enabled without permitting deletion of the old/current VPS. Old VPS cleanup
requires all of the following at process start:

```env
ASO_DRY_RUN=false
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true
ASO_ALLOW_OLD_VPS_DELETION=true
ASO_OLD_VPS_DELETE_CONFIRMATION=DELETE_ONLY_VERIFIED_OLD_VPS
ASO_REPLACEMENT_EMERGENCY_STOP=false
```

Keep `ASO_ALLOW_OLD_VPS_DELETION=false` during initial live create/deploy/master-switch testing. A fully
verified job will wait at the cleanup checkpoint instead of deleting the old VPS. Enable the deletion
gate only after an operator has verified the new node and the provider registry mapping.
