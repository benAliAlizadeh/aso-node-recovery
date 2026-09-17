from app.core.errors import AsoError


class ReplacementError(AsoError):
    """Base error for the persisted replacement workflow."""


class ReplacementBusyError(ReplacementError):
    pass


class ReplacementDeferredError(ReplacementError):
    """External state is ambiguous/incomplete; retry later without marking the job failed."""


class ReplacementConfigurationError(ReplacementError):
    pass
