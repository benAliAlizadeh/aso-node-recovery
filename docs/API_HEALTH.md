# API Health Center

The Telegram API Health Center performs read-only, authenticated diagnostics against the external
services ASO depends on. Open it from **❤️ API Health** or run `/apihealth`.

Checks include:

- PostgreSQL (`SELECT 1`)
- Check-Host node discovery for the configured country (Iran by default)
- Telegram Bot API authentication (`getMe`)
- Master 3X-UI API authentication and node listing
- every registered Hetzner/Linode provider using its read-only access probe
- every registered 3X-UI node API using its stored token and the endpoint discovered from Master

Each result shows status, latency, and a bounded diagnostic message. Credentials are never rendered.
The health service contains no provider create/delete/reboot, Master update, or replacement calls.

Two optional settings control diagnostics:

```env
ASO_API_HEALTH_TIMEOUT_SECONDS=12
ASO_API_HEALTH_MAX_CONCURRENCY=8
```

A failed health check is diagnostic only. It does not change Node state and does not trigger recovery.
