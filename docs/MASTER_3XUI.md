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

## Master connection routing

ASO supports both deployment layouts without changing the stored Master URL:

- `ASO_MASTER_3XUI_CONNECTION_MODE=auto` (default): probe the configured/public Master TCP
  endpoint first. If that transport is unreachable, probe the Docker host gateway and use it for
  the current client only. Authentication/HTTP/API errors never trigger fallback.
- `remote`: always use `ASO_MASTER_3XUI_BASE_URL`; no same-host fallback.
- `local-host`: route directly through `host.docker.internal` while preserving scheme, port, base
  path, and the original Host header.

The production Compose stack maps `host.docker.internal` to Docker's `host-gateway`, so a 3X-UI
Master listening on the same Linux server can be reached from the ASO containers. The canonical
`ASO_MASTER_3XUI_BASE_URL` is never overwritten by automatic routing.

For same-host HTTPS layouts where the local transport differs from the public URL (for example the
public endpoint terminates TLS in a reverse proxy while 3X-UI itself listens on local HTTP), set an
explicit transport override such as:

```env
ASO_MASTER_3XUI_CONNECTION_MODE=auto
ASO_MASTER_3XUI_LOCAL_BASE_URL=http://host.docker.internal:2053/QAZ
```

Remote deployments normally need no extra setting; their configured Master URL remains the selected
route as long as its TCP endpoint is reachable.
