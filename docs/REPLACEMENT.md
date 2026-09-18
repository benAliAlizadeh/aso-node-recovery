# Replacement Orchestrator

Phase 6 connects the already-isolated monitoring, provider, deployment, and master adapters into one
persisted recovery workflow. The workflow is deliberately checkpointed: a process restart resumes
from database state instead of blindly repeating cloud mutations.

## Durable checkpoints

```text
created
  -> provisioning
  -> provisioned
  -> checking_ip
      -> temp_cleanup -> provisioning   (bad candidate, bounded retry)
      -> ip_verified
  -> deploying
  -> node_verified
  -> master_updating
  -> master_updated
  -> master_verifying
  -> master_verified
  -> final_check
  -> final_verified
  -> old_vps_cleanup
  -> completed
```

Every active checkpoint may terminate as `failed` or `cancelled`. Terminal jobs release their active
slot. A per-job database lease prevents overlapping workers, and the existing unique
`(node_id, active_slot)` constraint remains the final database-level per-node guard.

## Crash recovery and idempotency

Replacement VPS names are deterministic for a job/attempt. Before issuing a create call the adapter
searches the provider for that exact name/label. This covers the ambiguous window where the provider
may have created a server but ASO crashed or timed out before persisting the response.

The sequence is:

1. persist `provisioning_requested_at`;
2. search provider for the deterministic candidate name;
3. create only when no candidate is found and the reconciliation grace period has expired;
4. persist provider server identity immediately;
5. wait for readiness as a separate operation.

A transient create error is therefore deferred, not blindly retried. The next worker cycle reconciles
provider state first.

Deployment is also resumable. Its persisted state controls whether ASO waits for SSH, bootstraps,
installs, or only verifies an installation that may already exist.

## Master 3X-UI switch

The local `nodes.master_node_id` is the only mapping used. IP addresses are never used as identity.
Before changing the existing master node, ASO:

1. reads the mapped node;
2. persists a rollback snapshot without credentials;
3. verifies that a rollback API-token reference exists when required;
4. refuses transitive or mTLS nodes rather than silently weakening security;
5. probes the replacement through the master `/panel/api/nodes/test` contract;
6. updates the existing node;
7. reads/probes it again and compares the persisted target fields.

Node API tokens are write-only in current 3X-UI. Generated replacement tokens/passwords are written
to owner-only runtime secret files; database rows contain references only.

If post-switch verification or the final reachability check fails, ASO attempts to restore the
persisted master snapshot while the old VPS is still alive. A failed/ambiguous rollback never permits
old-VPS deletion.

## Old VPS hard gate

`OldVpsProtectionGuard` is the only intended old-server deletion gate. It rejects deletion unless all
of these persisted conditions are present:

- distinct replacement VPS exists and is running;
- replacement IP verification succeeded;
- deployment state is `succeeded`;
- deployment verification timestamp exists;
- master update timestamp exists;
- master verification timestamp exists;
- final reachability verification timestamp exists.

Only after the guard passes does the orchestrator call the old VPS provider adapter. In the safety-hardened
release, cleanup also requires `ASO_ALLOW_OLD_VPS_DELETION=true` plus the exact confirmation phrase
`DELETE_ONLY_VERIFIED_OLD_VPS`. Immediately before deletion, ASO reads the provider object again and
requires its provider ID and public IPv4 to match the persisted old-VPS registry identity. A mismatch
refuses deletion. A provider 404 at this exact checkpoint is treated as idempotent crash recovery (for
example, crash after the cloud deleted the server but before the database commit).

## Reachability ambiguity

`INDETERMINATE` Check-Host results are never treated as a bad IP. They defer the job. Only an explicit
`UNREACHABLE` quorum may delete the **new temporary** VPS and consume another attempt.

## DRY_RUN behavior

`ASO_DRY_RUN=true` remains the default. Dry-run jobs may simulate provider/deployment/checkpoint
progress, but they do not contact the master, do not delete the registered old VPS, do not promote a
replacement to current, and do not mark the real node healthy. Automatic triggering of new failed
nodes is also suppressed in dry-run; a simulation must be explicitly triggered by a control layer.

## Emergency stop

`ASO_REPLACEMENT_EMERGENCY_STOP=true` causes active workflows to defer before the next external
mutation. It does not convert uncertainty into failure and does not perform cleanup while stopped.

## Required provider/node registry data

Before real replacement is enabled:

- Provider needs `default_region`, `default_server_type`, and `default_image`.
- Private-key SSH nodes need `node_credentials.ssh_public_key` in addition to the private-key secret
  reference used by AsyncSSH.
- Linode password bootstrap can reuse the referenced root password. Hetzner password-only bootstrap is
  intentionally rejected; configure a public key instead.
- The current VPS must exist in `vps_instances` with role `current`.
- Safe master rollback requires the old node API-token reference when the master says a token is set.

Permanent spare VPS/IP pools are not used.
