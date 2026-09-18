# Operational onboarding

Installation starts the ASO services in a deliberately locked state. A fresh database has no
provider or node inventory yet, so Telegram `/nodes` and `/providers` will remain empty until the
existing infrastructure is registered.

## 1. Run the non-destructive setup wizard

```bash
./asoctl setup
```

The wizard can configure the Master connection and register:

- Hetzner or Linode provider account metadata,
- the provider's default replacement region/type/image,
- each existing Master 3X-UI node ID,
- the current node IP/panel port,
- the **existing VPS provider server/instance ID**,
- SSH credentials used to bootstrap a replacement,
- the current node API token for safe Master rollback when available.

Secrets are either kept in the protected `.env` or imported into the persistent runtime-secret
volume. The database stores secret references rather than raw SSH private keys or node API tokens.

The wizard does **not** create/delete a VPS, mutate the Master, or enable replacement workers.

## 2. Verify registry and Telegram

```bash
./asoctl registry
./asoctl health
./asoctl telegram-check
```

Then open the bot and send `/start`. The bot should show providers/nodes and an inline menu.

## 3. Test one node manually

Keep the safety defaults locked and run:

```text
/nodes
/check <node-name>
```

A manual check uses Check-Host monitoring. It does not authorize a real provider mutation.

## 4. Optional automatic monitoring-only mode

After the inventory is correct:

```bash
./asoctl monitoring-dry-run
```

This explicitly keeps:

```env
ASO_DRY_RUN=true
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false
ASO_ALLOW_OLD_VPS_DELETION=false
ASO_REPLACEMENT_WORKER_ENABLED=false
ASO_REPLACEMENT_EMERGENCY_STOP=true
```

and enables only the monitoring scheduler. Disable it with:

```bash
./asoctl monitoring-off
```

Real replacement remains a separate, explicitly authorized production step.
