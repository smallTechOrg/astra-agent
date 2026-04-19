"""Cadence registry — maps cadence type string to Cadence class."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra.cadences.base import Cadence

_REGISTRY: dict[str, type[Cadence]] = {}


def register_cadence(cadence_type: str, cls: type[Cadence]) -> None:
    _REGISTRY[cadence_type] = cls


def get_cadence(cadence_type: str) -> type[Cadence]:
    try:
        return _REGISTRY[cadence_type]
    except KeyError:
        from astra.errors import AstraError
        raise AstraError(
            f"Unknown cadence type {cadence_type!r}. Registered: {sorted(_REGISTRY)}"
        ) from None
