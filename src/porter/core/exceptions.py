class PorterError(Exception):
    """Base error for Porter."""


class ProviderError(PorterError):
    """Expected provider failure eligible for fallback."""


class NoProviderAvailable(PorterError):
    """No approved provider could satisfy the request."""


class InferenceConfirmationRequired(PorterError):
    """Inference escalation requires an explicit caller decision."""


class InferenceDeclined(PorterError):
    """The caller declined an otherwise eligible inference escalation."""


class ActionNotAuthorized(PorterError):
    """A recognized deterministic action is not permitted for this request source."""
