class AsoError(Exception):
    """Base exception for expected application errors."""


class ConfigurationError(AsoError):
    """Raised when application configuration is invalid for an operation."""


class SafetyViolationError(AsoError):
    """Raised when an operation violates an ASO safety invariant."""
