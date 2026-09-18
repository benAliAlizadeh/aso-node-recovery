from enum import StrEnum


class ProviderType(StrEnum):
    HETZNER = "hetzner"
    LINODE = "linode"


class NodeState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    REPLACING = "replacing"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    DISABLED = "disabled"


class SshAuthMethod(StrEnum):
    PRIVATE_KEY = "private_key"
    PASSWORD = "password"


class SecretReferenceBackend(StrEnum):
    """Where secret material is resolved from; the database stores references only."""

    ENVIRONMENT = "environment"
    FILE = "file"
    EXTERNAL = "external"
    DATABASE_ENCRYPTED = "database_encrypted"


class NodeCheckOutcome(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    INDETERMINATE = "indeterminate"
    ERROR = "error"


class ReplacementJobState(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    CHECKING_IP = "checking_ip"
    DEPLOYING = "deploying"
    UPDATING_MASTER = "updating_master"
    VERIFYING = "verifying"
    CLEANING_UP = "cleaning_up"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplacementCheckpoint(StrEnum):
    CREATED = "created"
    PROVISIONING = "provisioning"
    PROVISIONED = "provisioned"
    CHECKING_IP = "checking_ip"
    TEMP_CLEANUP = "temp_cleanup"
    IP_VERIFIED = "ip_verified"
    DEPLOYING = "deploying"
    NODE_VERIFIED = "node_verified"
    MASTER_UPDATING = "master_updating"
    MASTER_UPDATED = "master_updated"
    MASTER_VERIFYING = "master_verifying"
    MASTER_VERIFIED = "master_verified"
    FINAL_CHECK = "final_check"
    FINAL_VERIFIED = "final_verified"
    OLD_VPS_CLEANUP = "old_vps_cleanup"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VpsInstanceState(StrEnum):
    PROVISIONING = "provisioning"
    RUNNING = "running"
    DELETING = "deleting"
    DELETED = "deleted"
    ERROR = "error"


class VpsInstanceRole(StrEnum):
    CURRENT = "current"
    REPLACEMENT = "replacement"


class DeploymentState(StrEnum):
    PENDING = "pending"
    WAITING_SSH = "waiting_ssh"
    BOOTSTRAPPING = "bootstrapping"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventType(StrEnum):
    NODE_FAILED = "node_failed"
    NODE_RECOVERED = "node_recovered"
    NODE_DEGRADED = "node_degraded"
    MONITORING_CHECK_ERROR = "monitoring_check_error"
    REPLACEMENT_STARTED = "replacement_started"
    VPS_CREATED = "vps_created"
    IP_CHECK_STARTED = "ip_check_started"
    IP_CHECK_FAILED = "ip_check_failed"
    IP_CHECK_PASSED = "ip_check_passed"
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_FAILED = "deployment_failed"
    MASTER_UPDATED = "master_updated"
    MASTER_VERIFIED = "master_verified"
    OLD_VPS_DELETED = "old_vps_deleted"
    REPLACEMENT_COMPLETED = "replacement_completed"
    REPLACEMENT_FAILED = "replacement_failed"
    CONTROL_ACTION = "control_action"
    SETTING_CHANGED = "setting_changed"
    SYSTEM_PAUSED = "system_paused"
    SYSTEM_RESUMED = "system_resumed"
    PROVIDER_UPDATED = "provider_updated"
