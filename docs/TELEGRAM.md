# Telegram control plane

Telegram is a presentation/control surface only. Provider, monitoring, replacement, and database
business logic remains in application services.

## Required configuration

- `ASO_TELEGRAM_BOT_ENABLED=true`
- `ASO_TELEGRAM_BOT_TOKEN`
- `ASO_TELEGRAM_AUTHORIZED_USER_IDS=[...]`
- `ASO_TELEGRAM_CALLBACK_SECRET` (independent random secret, 32+ characters)
- optional `ASO_TELEGRAM_NOTIFICATION_CHAT_ID`

All commands reject users outside the allow-list.

## Commands

- `/start`
- `/status`
- `/nodes`
- `/node <uuid|name>`
- `/check <uuid|name>`
- `/replace <uuid|name>`
- `/jobs`
- `/logs`
- `/settings`
- `/providers`
- `/pause`
- `/resume`

Manual replacement, replacement resume/cancel, and provider enable/disable use short-lived,
user-bound HMAC confirmations. A forwarded/stale confirmation cannot be reused by another user.

`/pause` is persisted in PostgreSQL. Monitoring and replacement workers stop starting work, and a
running replacement checks the pause flag between durable checkpoints. Cancellation remains
available so an operator can safely cancel a pre-master-switch job.

## Notifications

When `ASO_TELEGRAM_NOTIFICATION_CHAT_ID` is set, the bot polls the append-only event log and sends
notifications for node failures/recoveries and replacement lifecycle events. The notification cursor
is persisted in the settings table so bot restarts do not intentionally replay the entire audit log.
