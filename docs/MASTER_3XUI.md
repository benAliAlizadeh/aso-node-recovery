# Master 3X-UI Client

The Phase 6 master adapter is based on the current 3X-UI node API contract verified during this
milestone. It supports Bearer API-token authentication and the current username/password login
fallback.

The replacement path uses:

- `GET /panel/api/nodes/get/{id}`
- `POST /panel/api/nodes/test`
- `POST /panel/api/nodes/update/{id}`
- `POST /panel/api/nodes/probe/{id}`
- `POST /panel/api/nodes/certFingerprint` when an existing HTTPS node uses certificate pinning

The update mutation preserves the existing node's non-connection policy fields while replacing only
the connection data required by the new node: scheme/address/port/base path/API token (and a refreshed
certificate pin when applicable).

3X-UI node API tokens are treated as write-only. Read responses are represented as `hasApiToken`, and
rollback snapshots never contain token/password material.

Master network/5xx failures are classified as transient so the persisted workflow can defer and
reconcile instead of assuming an update did or did not happen. Post-update verification re-reads the
node and probes it before the old VPS deletion checkpoint becomes reachable.
