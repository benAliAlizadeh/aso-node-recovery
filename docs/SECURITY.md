# Security controls

- `DRY_RUN=true` and `ALLOW_REAL_INFRASTRUCTURE_MUTATION=false` are safe defaults.
- Production configuration refuses disabled SSH host-key verification or disabled TLS verification
  for node/master 3X-UI.
- Telegram access is an explicit user-ID allow-list.
- Destructive Telegram confirmations are user-bound, HMAC signed, and expire.
- Provider credentials, Master credentials, Telegram token, SSH secrets, and generated 3X-UI tokens
  are never stored as plaintext audit payloads.
- Provider credentials are secret references; generated node secrets are owner-only files.
- The old VPS deletion path remains protected by the Phase 6 durable verification gates.
- Docker production application containers run non-root, drop Linux capabilities, use
  `no-new-privileges`, read-only root filesystems, bounded PIDs/CPU/memory, and log rotation.
- PostgreSQL is not published to the host in the production Compose file.
- Database restore has an independent disabled-by-default gate and confirmation phrase.

Run:

```bash
python scripts/security_review.py
```

before changing either real-infrastructure guard.
