from app.core.errors import AsoError


class Master3XUiError(AsoError):
    """Base error for master panel communication/validation failures."""


class MasterTransientError(Master3XUiError):
    """Retryable network/server ambiguity. The caller should reconcile before mutating again."""


class MasterAuthenticationError(Master3XUiError):
    pass


class MasterNodeVerificationError(Master3XUiError):
    pass
