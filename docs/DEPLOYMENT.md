# Deployment Layer — Phase 5

## Workflow

The deployment engine operates only on an already-created replacement VPS:

```text
PENDING
  -> WAITING_SSH
  -> BOOTSTRAPPING
  -> INSTALLING
  -> VERIFYING
  -> SUCCEEDED
```

Any active step may transition to `FAILED`. Skipping steps is rejected by
`DeploymentStateMachine`.

## SSH

`AsyncSshCommandExecutor` is the only AsyncSSH-specific component. It supports password and private
key authentication and deliberately does not log command stdout/stderr because install results can
contain credentials.

Host-key verification is enabled by default. A known-hosts path can be configured for automated
replacement hosts. Disabling verification requires an explicit configuration change and is not the
default.

`SshReadinessProbe` performs bounded retries before deployment starts.

## OS bootstrap

The remote OS is detected from `/etc/os-release` plus `uname -m`. Bootstrap installs only the small
set of prerequisites required by the upstream installer (`curl` and CA certificates), with commands
selected by package-manager family.

## 3X-UI installation

All 3X-UI shell behavior is isolated in `ThreeXUiInstaller`.

The current upstream installer supports unattended operation with `XUI_NONINTERACTIVE=1`. It generates
unique credentials and writes a root-only result file at:

```text
/etc/x-ui/install-result.env
```

ASO consumes these current upstream fields:

- `XUI_USERNAME`
- `XUI_PASSWORD`
- `XUI_PANEL_PORT`
- `XUI_WEB_BASE_PATH`
- `XUI_ACCESS_URL`
- `XUI_API_TOKEN`
- `XUI_DB_TYPE`

The resulting password and API token are held as `SecretStr` values and are not included in command
strings or log messages.

## Node API verification

After local service verification and configuration extraction, ASO calls the current token-authenticated
3X-UI server status endpoint:

```text
<panel-access-url>/panel/api/server/status
```

A successful envelope and `xray.state == running` are required before deployment is marked successful.

## Rollback

Deployment rollback is intentionally conservative. It may stop a partially installed `x-ui` service
and remove ASO's temporary installer file on the **new replacement VPS only**. It does not delete any
VPS and has no access to the old VPS. VPS lifecycle cleanup remains the provider/orchestrator's
responsibility.

## DRY_RUN

When `ASO_DRY_RUN=true`, `DeploymentService` advances a test deployment through its state machine but
performs no SSH connection and executes no remote command. Real SSH/deployment additionally requires:

```text
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true
```
