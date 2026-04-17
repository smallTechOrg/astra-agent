"""Destination registry — maps platform string to Destination class."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra.destinations.base import Destination

_REGISTRY: dict[str, type[Destination]] = {}


def register_destination(platform: str, cls: type[Destination]) -> None:
    _REGISTRY[platform] = cls


def get_destination(platform: str) -> type[Destination]:
    try:
        return _REGISTRY[platform]
    except KeyError:
        from astra.errors import DestinationError
        raise DestinationError(
            f"Unknown destination platform {platform!r}. Registered: {sorted(_REGISTRY)}"
        ) from None
