"""Logging gate: SecretStr values and secret-named keys are never logged raw.

Gate from reports/2026-04-17-v0.1-greenfield-implementation.md, phase 3:
  'Unit tests assert that logging a config or exception never serialises a
  SecretStr raw value (uses pydantic's redaction).'
"""

from __future__ import annotations

import pytest  # noqa: TC002
from pydantic import SecretStr

from astra.logging import _redact_secrets, configure_logging, get_logger

# ── SecretStr redaction ──────────────────────────────────────────

def test_secretstr_repr_is_redacted() -> None:
    s = SecretStr("s3cr3t")
    assert "s3cr3t" not in repr(s)
    assert "s3cr3t" not in str(s)


def test_secretstr_not_in_str_of_dict() -> None:
    d = {"access_token": SecretStr("tok123")}
    assert "tok123" not in str(d)
    assert "tok123" not in repr(d)


def test_secretstr_not_in_exception_message() -> None:
    s = SecretStr("hunter2")
    exc = ValueError(f"got token={s}")
    assert "hunter2" not in str(exc)


# ── _redact_secrets processor ────────────────────────────────────

def test_redact_processor_masks_secret_key() -> None:
    event = {"event": "test", "access_token": "plaintext_value"}
    result = _redact_secrets(None, "info", event)  # type: ignore[arg-type]
    assert result["access_token"] == "**redacted**"


def test_redact_processor_masks_various_key_suffixes() -> None:
    event = {
        "event": "test",
        "api_key": "k1",
        "client_secret": "s1",
        "db_password": "p1",
        "oauth_token": "t1",
        "refresh_credential": "c1",
    }
    result = _redact_secrets(None, "info", event)  # type: ignore[arg-type]
    for k in ("api_key", "client_secret", "db_password", "oauth_token", "refresh_credential"):
        assert result[k] == "**redacted**", f"{k} was not redacted"


def test_redact_processor_preserves_non_secret_keys() -> None:
    event = {"event": "test", "tenant_id": "acme", "url": "https://x.example"}
    result = _redact_secrets(None, "info", event)  # type: ignore[arg-type]
    assert result["tenant_id"] == "acme"
    assert result["url"] == "https://x.example"


# ── configure_logging / get_logger ──────────────────────────────

def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    import astra.logging as al

    monkeypatch.setattr(al, "_configured", False)
    configure_logging(json=False)
    configure_logging(json=False)  # second call is a no-op, no exception


def test_get_logger_has_bind_method() -> None:
    log = get_logger("astra.test")
    assert callable(getattr(log, "bind", None))


def test_get_logger_bind_returns_new_logger() -> None:
    log = get_logger("astra.test")
    bound = log.bind(tenant_id="acme")
    assert bound is not log
