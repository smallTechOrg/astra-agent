"""Source abstraction and registry.

Per spec/product/02-architecture.md#source and spec/product/09-extensibility.md:
one abstract Source, registry keyed on source.type string.
"""

from __future__ import annotations

from astra.sources.base import Source
from astra.sources.registry import get_source, register_source
from astra.sources.wordpress import WordPressSource

# Register built-in source on import.
register_source("wordpress", WordPressSource)

__all__ = ["Source", "WordPressSource", "get_source", "register_source"]
