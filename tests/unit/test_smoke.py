from __future__ import annotations

from astra import __version__


def test_version_is_v0_1_0() -> None:
    assert __version__ == "0.1.0"
