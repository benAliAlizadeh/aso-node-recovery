# Runtime Controls

Patch 16 adds persistent runtime controls without weakening host safety.

## Per-node mode

Each node has exactly one operating mode:

- `disabled`: scheduled monitoring and automatic repair are disabled for the node.
- `monitor_only`: Check-Host monitoring runs, but automatic replacement is never triggered.
- `auto_repair`: monitoring runs and the node is eligible for automatic replacement when the global Auto Repair worker is enabled.

Changing a node mode is refused while that node has an active replacement job.

## Global controls

Telegram `/controls` exposes:

- Monitoring ON/OFF
- Auto Repair worker ON/OFF
- Runtime DRY RUN / LIVE intent

The worker process keeps lightweight scheduler jobs registered and reads the persisted switches on each cycle, so ordinary runtime toggles do not require a container restart.

## Safety boundary

Telegram cannot make a host live-capable. LIVE is accepted only when all host-level gates already allow it:

```env
ASO_DRY_RUN=false
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true
ASO_REPLACEMENT_EMERGENCY_STOP=false
```

If those gates are not satisfied, effective execution remains DRY RUN even if a stale database value requests LIVE.

`ASO_ALLOW_OLD_VPS_DELETION` remains a separate final cleanup gate and is never changed from Telegram.

## Automatic repair behavior

Automatic repair requires all of the following:

1. the node mode is `auto_repair`,
2. global monitoring is enabled,
3. global Auto Repair worker is enabled,
4. the node reaches FAILED through the monitoring thresholds,
5. effective execution is LIVE,
6. host safety gates allow real infrastructure mutation.

In DRY RUN, automatic repair does not create repeated simulated jobs. Operators may still use explicit manual replacement simulations.
