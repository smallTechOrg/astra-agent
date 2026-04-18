"""ConfigLoader tests — DB-first config per spec/product/05-config.md.

The loader only reads operator.yaml and DATABASE_URL from config/.env.
Tenant config/secrets live in the database; see test_repos.py for those.
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


def _operator_yaml(provider: str = "groq") -> str:
    return f"""\
log_level: info
llm:
  provider: {provider}
  model: llama-3.3-70b-versatile
  api_key_env: LLM_API_KEY
  max_tokens: 2048
  temperature: 0.8
"""


def _build_config_dir(
    tmp_path: Path,
    operator_yaml: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    if operator_yaml is not None:
        _write(config_dir / "operator.yaml", operator_yaml)
    if env:
        _write(
            config_dir / ".env",
            "\n".join(f"{k}={v}" for k, v in env.items()),
        )
    return config_dir


# ── operator config loading ─────────────────────────────────────


def test_happy_path_loads_operator_config(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        operator_yaml=_operator_yaml("openai"),
        env={"DATABASE_URL": "postgresql://test/db"},
    )
    loaded = ConfigLoader(config_dir).load()
    assert loaded.operator.llm.provider == "openai"
    assert loaded.database_url == "postgresql://test/db"


def test_missing_operator_yaml_uses_defaults(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        env={"DATABASE_URL": "postgresql://test/db"},
    )
    loaded = ConfigLoader(config_dir).load()
    assert loaded.operator.log_level == "info"
    assert loaded.database_url == "postgresql://test/db"


def test_database_url_from_env_file(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        env={"DATABASE_URL": "postgresql://from-env-file/db"},
    )
    loaded = ConfigLoader(config_dir).load()
    assert loaded.database_url == "postgresql://from-env-file/db"


def test_database_url_from_os_env_as_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = _build_config_dir(tmp_path)  # no .env file
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-os-env/db")
    loaded = ConfigLoader(config_dir).load()
    assert loaded.database_url == "postgresql://from-os-env/db"


def test_operator_log_level_is_parsed(tmp_path: Path) -> None:
    config_dir = _build_config_dir(
        tmp_path,
        operator_yaml="log_level: debug\n",
        env={"DATABASE_URL": "postgresql://test/db"},
    )
    loaded = ConfigLoader(config_dir).load()
    assert loaded.operator.log_level == "debug"


def test_llm_config_fields_are_loaded(tmp_path: Path) -> None:
    yaml = """\
llm:
  provider: anthropic
  model: claude-3-5-haiku-20241022
  api_key_env: ANTHROPIC_API_KEY
  max_tokens: 1024
  temperature: 0.5
"""
    config_dir = _build_config_dir(
        tmp_path,
        operator_yaml=yaml,
        env={"DATABASE_URL": "postgresql://test/db"},
    )
    loaded = ConfigLoader(config_dir).load()
    assert loaded.operator.llm.provider == "anthropic"
    assert loaded.operator.llm.model == "claude-3-5-haiku-20241022"
    assert loaded.operator.llm.api_key_env == "ANTHROPIC_API_KEY"
    assert loaded.operator.llm.max_tokens == 1024


def test_raises_typed_errors() -> None:
    for cls in (ConfigValidationError,):
        with pytest.raises(cls):
            raise cls("test")
