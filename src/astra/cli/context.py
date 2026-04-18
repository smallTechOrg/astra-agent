"""Shared CLI context and helpers.

Holds the resolved config_dir and loaded config so subcommands don't reload it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from astra.config.loader import LoadedConfig


@dataclass
class AstraContext:
    config_dir: Path
    json_log: bool = False
    verbosity: int = 0
    _loaded_config: LoadedConfig | None = field(default=None, repr=False)

    def load_config(self) -> LoadedConfig:
        if self._loaded_config is None:
            from astra.config.loader import ConfigLoader
            self._loaded_config = ConfigLoader(self.config_dir).load()
        return self._loaded_config

    @property
    def database_url(self) -> str:
        return self.load_config().database_url
