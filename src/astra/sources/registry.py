"""Source registry — maps source.type string to Source class."""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.errors import UnknownSourceTypeError

if TYPE_CHECKING:
    from astra.sources.base import Source

_REGISTRY: dict[str, type[Source]] = {}


def register_source(type_name: str, cls: type[Source]) -> None:
    _REGISTRY[type_name] = cls


def get_source(type_name: str) -> type[Source]:
    try:
        return _REGISTRY[type_name]
    except KeyError:
        raise UnknownSourceTypeError(
            f"Unknown source type {type_name!r}. Registered: {sorted(_REGISTRY)}"
        ) from None
