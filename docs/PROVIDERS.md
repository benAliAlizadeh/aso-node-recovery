# Provider Layer — Phase 4

## Boundary

Provider-specific HTTP formats stay inside `app/providers/`. The replacement workflow consumes only
`ProviderAdapter` and provider-neutral request/result types.

Implemented adapters:

- Hetzner Cloud API (`https://api.hetzner.cloud/v1`)
- Akamai Cloud / Linode API v4 (`https://api.linode.com/v4`)
- `DryRunProvider` for development and ordinary tests

The adapters support create, read/status, IPv4 retrieval, delete, reboot, and bounded readiness
polling. Provider response errors are mapped into normalized ASO exceptions so later orchestration can
make retry decisions without knowing provider-specific payload formats.

## Current documented API shapes

Hetzner uses the Cloud API server endpoints under `/servers`, including server creation and server
actions such as reboot. Location is used rather than the deprecated datacenter request field.

Linode uses API v4 `/linode/instances`. Image deployment requires at least one access mechanism:
`authorized_keys`, `authorized_users`, or `root_pass`. ASO supports SSH public keys and an optional
root password in the provider-neutral creation request. Delete and reboot use the documented instance
endpoints.

## Safety

Two independent switches protect real infrastructure:

```text
ASO_DRY_RUN=true
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false
```

While `DRY_RUN=true`, `ProviderFactory` returns `DryRunProvider` before resolving a real API token, so
ordinary development cannot accidentally contact a provider.

To receive a real provider adapter, both conditions must be true:

```text
ASO_DRY_RUN=false
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true
```

This patch never enables either switch automatically.

## Bounded provisioning

`ProvisioningSafetyPolicy` enforces:

- maximum replacement attempts
- maximum temporary VPS count
- maximum concurrent replacements

`ProvisioningService` separates creation from readiness. Phase 6 will persist the returned provider
server ID immediately after `create_temporary()` before it waits for readiness. The service has no
old/current VPS identifier; cleanup accepts only an explicitly tracked temporary provider server ID.

Provider retry classification is separated from execution. ASO does **not** blindly repeat a server
creation POST after an ambiguous timeout because the provider may have created the server even though
the response was lost. Phase 6 crash recovery/idempotency will reconcile provider state before
creating another VPS.

## Secret handling

Database provider records store only a secret reference. `SecretResolver` currently supports:

- environment variable references
- file references

External secret managers and database-encrypted secret storage intentionally fail closed until a real
adapter is implemented. Raw API tokens are never modeled as provider database columns.
