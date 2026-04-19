"""Shared CLI context and helpers.

Holds the resolved config_dir and bootstrap values so subcommands don't reload them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class AstraContext:
    config_dir: Path
    json_log: bool = False
    verbosity: int = 0
    _database_url: str | None = field(default=None, repr=False)

    @property
    def database_url(self) -> str:
        if self._database_url is None:
            from astra.config.loader import ConfigLoader
            self._database_url = ConfigLoader(self.config_dir).load_bootstrap()
        return self._database_url
