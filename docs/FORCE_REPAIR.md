# Force Repair

Force Repair is an operator-initiated replacement workflow for a registered node that may still be
reachable from Iran. It is intended for maintenance cases where the operator wants to rotate the VPS
without waiting for the normal failure threshold.

## What Force Repair bypasses

Only the initial `NodeState.FAILED` admission requirement is bypassed.

## What Force Repair does not bypass

The normal replacement workflow is reused unchanged after admission. The following remain mandatory:

- global replacement admission/concurrency limits,
- current VPS identity in the ASO registry,
- active Provider validation,
- replacement VPS provisioning limits,
- new IP Iran reachability verification,
- SSH readiness and 3X-UI deployment verification,
- Master 3X-UI preflight/update/verification,
- final Iran reachability verification,
- the independent old-VPS deletion switch,
- old-VPS provider ID/IP re-verification immediately before deletion.

A disabled node cannot be force repaired. An already active replacement job is reused rather than
creating a second job.

## Telegram

Use the `⚠️ Force Repair` button on a node or:

```text
/force <uuid|name>
```

The confirmation callback is signed, bound to the authorized Telegram user, time limited, and mapped
to a durable request key. Replaying the same confirmation returns the same replacement job instead of
creating a duplicate.

## Failure behavior

For a live force repair started from `HEALTHY`, `DEGRADED`, `UNKNOWN`, or `FAILED`, ASO records the
original state. If the workflow fails or is cancelled before the Master is switched, the original node
state is restored. After a Master switch, ASO uses the existing conservative replacement failure and
rollback behavior instead of assuming the original state is still valid.
