"""Typed exception hierarchy tests.

Gate (phase 3): every typed exception has a test.
"""

from __future__ import annotations

import pytest

from astra.errors import (
    AstraError,
    ConfigValidationError,
    CronParseError,
    DestinationAuthError,
    DestinationDuplicateContentError,
    DestinationError,
    DestinationPermanentError,
    DestinationPermissionError,
    DestinationRateLimitedError,
    DestinationTransientError,
    DestinationValidationError,
    DuplicateCadenceNameError,
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMTransientError,
    MissingSecretError,
    PromptNotFoundError,
    PromptVariableError,
    SecretInYamlError,
    TenantIdMismatchError,
    TenantNotFoundError,
    UnknownSourceTypeError,
)


def raises(exc_class: type[Exception], **kwargs: object) -> None:
    with pytest.raises(exc_class):
        raise exc_class("msg", **kwargs)  # type: ignore[call-arg]


def test_all_errors_are_astra_errors() -> None:
    classes = [
        ConfigValidationError, SecretInYamlError, TenantIdMismatchError,
        MissingSecretError, CronParseError, DuplicateCadenceNameError,
        UnknownSourceTypeError, TenantNotFoundError, PromptNotFoundError,
        PromptVariableError, LLMError, LLMAuthError, LLMRateLimitError,
        LLMTransientError, DestinationError, DestinationAuthError,
        DestinationPermissionError, DestinationRateLimitedError,
        DestinationDuplicateContentError, DestinationValidationError,
        DestinationTransientError, DestinationPermanentError,
    ]
    for cls in classes:
        assert issubclass(cls, AstraError), f"{cls.__name__} not subclass of AstraError"


def test_destination_rate_limited_carries_reset_at() -> None:
    exc = DestinationRateLimitedError("too many requests", reset_at="2026-01-01T00:15:00Z")
    assert exc.reset_at == "2026-01-01T00:15:00Z"
    assert "too many requests" in str(exc)


def test_destination_rate_limited_reset_at_optional() -> None:
    exc = DestinationRateLimitedError("rate limited")
    assert exc.reset_at is None


def test_llm_hierarchy() -> None:
    for cls in (LLMAuthError, LLMRateLimitError, LLMTransientError):
        assert issubclass(cls, LLMError)


def test_destination_hierarchy() -> None:
    for cls in (
        DestinationAuthError, DestinationPermissionError, DestinationRateLimitedError,
        DestinationDuplicateContentError, DestinationValidationError,
        DestinationTransientError, DestinationPermanentError,
    ):
        assert issubclass(cls, DestinationError)


def test_config_errors_are_catchable_as_astra_error() -> None:
    with pytest.raises(AstraError):
        raise ConfigValidationError("bad yaml")


def test_secret_in_yaml_error() -> None:
    with pytest.raises(SecretInYamlError, match="api_token"):
        raise SecretInYamlError("api_token found in config/tenants/acme/tenant.yaml")


def test_tenant_not_found_error() -> None:
    with pytest.raises(TenantNotFoundError):
        raise TenantNotFoundError("acme")


def test_prompt_variable_error() -> None:
    with pytest.raises(PromptVariableError):
        raise PromptVariableError("variable 'titile' not declared")
