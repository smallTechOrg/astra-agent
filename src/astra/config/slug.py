"""Tenant ID slug validation.

Per spec/product/03-tenancy.md#naming: slug is [a-z0-9][a-z0-9-]*[a-z0-9],
2-40 chars, immutable once created.
"""

from __future__ import annotations

import re

from astra.errors import ConfigValidationError

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")


def validate_slug(value: str) -> None:
    if not _SLUG.match(value):
        raise ConfigValidationError(
            f"invalid tenant id {value!r}: must match [a-z0-9][a-z0-9-]*[a-z0-9], 2-40 chars"
        )
