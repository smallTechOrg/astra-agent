"""structlog setup for Astra.

Call `configure_logging(json=True/False)` once at daemon start (CLI main).
Thereafter every module obtains a logger with `get_logger(__name__)` and
binds `tenant_id` per the P6 rule in spec/engineering/tenant-isolation.md.

Secret hygiene (spec/engineering/secret-hygiene.md): pydantic SecretStr
values are never serialised by structlog because their __repr__ / __str__
return '**********'. The `_redact_secrets` processor adds an extra safety
net for any dict that somehow reaches the event_dict with a key that looks
like a secret name.
"""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from structlog.types import EventDict, WrappedLogger

_SECRET_KEY_RE = re.compile(
    r"_(token|secret|password|key|credential)$", re.IGNORECASE
)
_REDACTED = "**redacted**"

_configured = False


def _redact_secrets(
    logger: WrappedLogger, method: str, event_dict: EventDict
) -> EventDict:
    """Replace the *value* of any key that looks like a secret name."""

    for k in list(event_dict.keys()):
        if isinstance(k, str) and _SECRET_KEY_RE.search(k):
            event_dict[k] = _REDACTED
    return event_dict


def configure_logging(*, json: bool = False, level: str = "info") -> None:
    """Configure structlog globally. Safe to call multiple times; no-ops after first."""

    global _configured
    if _configured:
        return
    _configured = True

    import logging

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_secrets,
    ]

    if json:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to *name*.

    Usage::

        log = get_logger(__name__).bind(tenant_id=tenant_id)
        log.info("event_name", key="value")
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
