"""Destination abstraction and registry.

Per spec/product/02-architecture.md#destination and spec/product/09-extensibility.md.
"""

from __future__ import annotations

from astra.destinations.base import Destination
from astra.destinations.linkedin import LinkedInOrgDestination
from astra.destinations.registry import get_destination, register_destination
from astra.destinations.twitter import TwitterDestination

register_destination("linkedin", LinkedInOrgDestination)
register_destination("twitter", TwitterDestination)

__all__ = [
    "Destination",
    "LinkedInOrgDestination",
    "TwitterDestination",
    "get_destination",
    "register_destination",
]
