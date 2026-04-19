"""Typed exception hierarchy for Astra.

Every failure mode the spec names gets a typed exception so catchers can be
narrow. Bare RuntimeError/ValueError are prohibited by
spec/engineering/code-style.md.
"""

from __future__ import annotations


class AstraError(Exception):
    """Base for every Astra-raised exception."""


# ── Config / loader ─────────────────────────────────────────────

class ConfigValidationError(AstraError):
    """Config data failed pydantic validation."""


class SecretInYamlError(AstraError):
    """YAML contained a key whose name marks it a secret (*_token, *_secret, *_password, *_key)."""


class TenantIdMismatchError(AstraError):
    """tenant.yaml `id` field does not match the enclosing directory name."""


class MissingSecretError(AstraError):
    """An enabled destination/source references an env var that resolves to empty."""


class CronParseError(AstraError):
    """A *_cron field is not a valid 5-field cron expression."""


class DuplicateCadenceNameError(AstraError):
    """Two cadences within the same tenant share a `name`."""


class UnknownSourceTypeError(AstraError):
    """`source.type` does not match a registered Source implementation."""


class TenantNotFoundError(AstraError):
    """The operator referenced a tenant ID that isn't configured."""


# ── Prompt layer ────────────────────────────────────────────────

class PromptNotFoundError(AstraError):
    """No tenant override and no operator default exists for the prompt."""


class PromptVariableError(AstraError):
    """Declared/used variables don't match, or a required variable was not passed."""


# ── LLM layer ───────────────────────────────────────────────────

class LLMError(AstraError):
    """Base LLM failure."""


class LLMAuthError(LLMError):
    """The LLM provider rejected the API key."""


class LLMRateLimitError(LLMError):
    """429 from the LLM provider."""


class LLMTransientError(LLMError):
    """5xx or connection error from the LLM provider."""


# ── Destination layer ───────────────────────────────────────────

class DestinationError(AstraError):
    """Base destination failure."""


class DestinationAuthError(DestinationError):
    """401 from a destination — token likely expired."""


class DestinationPermissionError(DestinationError):
    """403 from a destination — access revoked or not granted."""


class DestinationRateLimitedError(DestinationError):
    """429 from a destination. Carries reset timestamp when the header was present."""

    def __init__(self, message: str, reset_at: str | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class DestinationDuplicateContentError(DestinationError):
    """Platform rejected the post as duplicate content (Twitter 403)."""


class DestinationValidationError(DestinationError):
    """Platform rejected the payload as malformed (LinkedIn 422)."""


class DestinationTransientError(DestinationError):
    """5xx or connection error from a destination."""


class DestinationPermanentError(DestinationError):
    """Destination returned a permanent failure not covered by the others."""
