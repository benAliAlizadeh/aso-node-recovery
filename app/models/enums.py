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
