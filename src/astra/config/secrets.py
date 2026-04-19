"""Minimal dotenv loading for bootstrap secrets.

Per spec/product/05-config.md: the only file-based secrets are DATABASE_URL
and ASTRA_UI_PASSWORD in config/.env. All other secrets live in the
operator_secrets / tenant_secrets DB tables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Minimal dotenv parser. Values with spaces are fine; no quoting required."""

    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        result[key] = value
    return result
