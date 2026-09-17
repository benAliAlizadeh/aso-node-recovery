from __future__ import annotations

from app.core.errors import AsoError


class ProviderError(AsoError):
    """Base provider adapter error safe for orchestration decisions."""

    retryable = False

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderNotFoundError(ProviderError):
    pass


class ProviderConflictError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    retryable = True


class ProviderTransientError(ProviderError):
    retryable = True


class ProviderTimeoutError(ProviderTransientError):
    pass
