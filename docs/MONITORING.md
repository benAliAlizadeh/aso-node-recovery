# Monitoring

## Check-Host protocol source

Implementation was verified against the official Check-Host API documentation on 2026-09-17:

https://check-host.net/about/api

Relevant documented calls:

- `GET /nodes/hosts` — current node list and locations
- `GET /check-tcp?host=<host:port>&node=<node>...` — start TCP check on explicit nodes
- `GET /check-result/<request_id>` — retrieve results

The documented API examples do not require an authentication header and the API page does not publish
a numeric rate limit. The client therefore does not invent either. Polling interval/timeout are
configurable and conservative.

## Iran-only selection

If `ASO_CHECK_HOST_NODES` is non-empty, those nodes are used. Otherwise the client retrieves the
current official node list and filters `location[0] == "ir"`, then selects up to
`ASO_CHECK_HOST_MAX_NODES`.

This avoids hard-coding a stale Iran node inventory.

## Normalization

Each selected Check-Host node is normalized to one of:

- `SUCCESS`
- `FAILURE`
- `PENDING`
- `MALFORMED`

For the documented TCP shape, an entry containing a numeric `time` and no `error` is success; an entry
containing `error` is failure; `null` is pending.

## Reachability quorum

Default:

```text
selected nodes: up to 5
minimum successes: 3
```

The target is `REACHABLE` as soon as the success quorum is met. It is `UNREACHABLE` only when enough
explicit failures exist that the quorum has become mathematically impossible. Otherwise it is
`INDETERMINATE`.

Therefore Check-Host outages, pending responses, malformed responses, or insufficient node coverage do
not increment node failure counters.

## Debounce

Default:

```text
FAILURE_THRESHOLD=3
RECOVERY_THRESHOLD=2
```

A failed probe does not immediately mark a node failed. A node becomes degraded first and reaches
`FAILED` only after the configured consecutive failure threshold. Recovery similarly requires
multiple successful checks.

Monitoring only changes health states (`UNKNOWN`, `HEALTHY`, `DEGRADED`, `FAILED`). Replacement and
deployment states are owned by later workflow phases.
