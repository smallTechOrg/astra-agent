"""Cadence abstraction and registry.

Per spec/product/02-architecture.md#cadence and spec/product/09-extensibility.md.
"""

from __future__ import annotations

from astra.cadences.base import Cadence
from astra.cadences.registry import get_cadence, register_cadence
from astra.cadences.twitter import TwitterCadence

register_cadence("twitter", TwitterCadence)

__all__ = ["Cadence", "TwitterCadence", "get_cadence", "register_cadence"]
