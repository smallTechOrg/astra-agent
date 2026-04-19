"""ConfigLoader tests — DB-first config per spec/product/05-config.md.

The loader reads DATABASE_URL and ASTRA_UI_PASSWORD from config/.env.
Operator config lives in the DB; see test_repos.py for those.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astra.config import ConfigLoader
from astra.errors import ConfigValidationError

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_config_dir(
    tmp_path: Path,
    env: dict[str, str] | None = None,
) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    if env:
        _write(
            config_dir / ".env",
            "\n".join(f"{k}={v}" for k, v in env.items()),
        )
    return config_dir


# ── bootstrap loading ───────────────────────────────────────────


def test_load_bootstrap_from_env_file(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        env={"DATABASE_URL": "postgresql://from-env-file/db"},
    )
    db_url = ConfigLoader(config_dir).load_bootstrap()
    assert db_url == "postgresql://from-env-file/db"


def test_load_bootstrap_from_os_env(tmp_path: Path) -> None:
    config_dir = _build_config_dir(tmp_path)
    loader = ConfigLoader(config_dir, os_env={"DATABASE_URL": "postgresql://from-os-env/db"})
    assert loader.load_bootstrap() == "postgresql://from-os-env/db"


def test_load_bootstrap_empty_warns(tmp_path: Path) -> None:
    config_dir = _build_config_dir(tmp_path)
    db_url = ConfigLoader(config_dir, os_env={}).load_bootstrap()
    assert db_url == ""


def test_load_ui_password_from_env_file(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        env={"ASTRA_UI_PASSWORD": "s3cret"},
    )
    assert ConfigLoader(config_dir).load_ui_password() == "s3cret"


def test_load_ui_password_none_when_missing(tmp_path: Path) -> None:
    config_dir = _build_config_dir(tmp_path)
    assert ConfigLoader(config_dir, os_env={}).load_ui_password() is None


def test_raises_typed_errors() -> None:
    for cls in (ConfigValidationError,):
        with pytest.raises(cls):
            raise cls("test")
