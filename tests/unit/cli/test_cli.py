"""CLI unit tests — per spec/product/06-cli.md.

Tenant management is now DB-backed; async internals are mocked so tests
do not require a running Postgres server.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import click
from click.testing import CliRunner

from astra.cli.main import main

if TYPE_CHECKING:
    from pathlib import Path

_TEST_DSN = "postgresql://astra:astra@localhost:5432/astra_test"


# ── helpers ──────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _operator_yaml() -> str:
    return """\
log_level: info
llm:
  provider: openai
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  max_tokens: 512
  temperature: 0.7
"""


def _build_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    _write(config_dir / "operator.yaml", _operator_yaml())
    _write(config_dir / ".env", f"OPENAI_API_KEY=sk-test\nDATABASE_URL={_TEST_DSN}\n")
    return config_dir


def _runner() -> CliRunner:
    return CliRunner()


def _mock_tenant_cfg(tenant_id: str = "acme", enabled: bool = True) -> object:
    from astra.config.models import TenantConfig

    return TenantConfig.model_validate({
        "id": tenant_id,
        "name": "Acme Corp",
        "enabled": enabled,
        "source": {"type": "wordpress", "url": "https://blog.acme.com"},
        "destinations": {
            "linkedin": {"enabled": True, "organization_id": "12345"},
            "twitter": {"enabled": False},
        },
        "cadences": [
            {"name": "daily", "cron": "0 9 * * *", "prompt": "twitter_cadence_daily"},
        ],
    })


def _mock_loaded_tenant(tenant_id: str = "acme", enabled: bool = True) -> MagicMock:
    loaded = MagicMock()
    loaded.config = _mock_tenant_cfg(tenant_id, enabled)
    loaded.degraded = False
    loaded.degraded_reason = None
    loaded.secrets = {}
    return loaded


# ── version ───────────────────────────────────────────────────────────────────


def test_version_cmd(tmp_path: Path) -> None:
    result = _runner().invoke(main, ["--config-dir", str(tmp_path / "config"), "version"])
    assert result.exit_code == 0
    assert "astra-agent" in result.output


# ── tenant add ────────────────────────────────────────────────────────────────


def test_tenant_add_creates_db_rows(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    with patch("astra.cli.tenant._create_tenant", new_callable=AsyncMock):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "add", "new-co"])
    assert result.exit_code == 0
    assert "Created tenant" in result.output


def test_tenant_add_invalid_id_exits_3(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "add", "BAD_ID"])
    assert result.exit_code == 3


def test_tenant_add_duplicate_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    async def _duplicate(*args: object, **kwargs: object) -> None:
        click.echo("Error: tenant 'acme' already exists.", err=True)
        sys.exit(1)

    with patch("astra.cli.tenant._create_tenant", new=_duplicate):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "add", "acme"])
    assert result.exit_code == 1


# ── tenant enable / disable ───────────────────────────────────────────────────


def test_tenant_enable_updates_db(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    with patch("astra.cli.tenant._set_enabled", new_callable=AsyncMock):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "enable", "acme"])
    assert result.exit_code == 0
    assert "enabled" in result.output


def test_tenant_disable_updates_db(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    with patch("astra.cli.tenant._set_enabled", new_callable=AsyncMock):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "disable", "acme"])
    assert result.exit_code == 0
    assert "disabled" in result.output


def test_tenant_enable_unknown_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    async def _not_found(*args: object, **kwargs: object) -> None:
        click.echo("Error: tenant 'ghost' not found.", err=True)
        sys.exit(1)

    with patch("astra.cli.tenant._set_enabled", new=_not_found):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "enable", "ghost"])
    assert result.exit_code == 1


# ── tenant list ───────────────────────────────────────────────────────────────


def test_tenant_list_shows_tenant(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    async def _list(database_url: str) -> None:
        click.echo("ID                   NAME                      ENABLED  PENDING")
        click.echo("-" * 60)
        click.echo("acme                 Acme Corp                 yes      0")

    with patch("astra.cli.tenant._list_tenants", new=_list):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "list"])
    assert result.exit_code == 0
    assert "acme" in result.output


def test_tenant_list_no_tenants(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    async def _empty(database_url: str) -> None:
        click.echo("No tenants configured.")

    with patch("astra.cli.tenant._list_tenants", new=_empty):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "list"])
    assert result.exit_code == 0
    assert "No tenants" in result.output


# ── tenant remove ─────────────────────────────────────────────────────────────


def test_tenant_remove_force_removes_db_rows(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    with patch("astra.cli.tenant._remove_tenant", new_callable=AsyncMock):
        result = _runner().invoke(
            main, ["--config-dir", str(config_dir), "tenant", "remove", "--force", "acme"]
        )
    assert result.exit_code == 0
    assert "removed" in result.output


def test_tenant_remove_unknown_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    async def _not_found(*args: object, **kwargs: object) -> None:
        click.echo("Error: tenant 'ghost' not found.", err=True)
        sys.exit(1)

    with patch("astra.cli.tenant._remove_tenant", new=_not_found):
        result = _runner().invoke(
            main, ["--config-dir", str(config_dir), "tenant", "remove", "--force", "ghost"]
        )
    assert result.exit_code == 1


# ── health ────────────────────────────────────────────────────────────────────


def test_health_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch(
            "astra.config.loader.ConfigLoader.load_tenants_from_db",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = _runner().invoke(
            main, ["--config-dir", str(config_dir), "health", "--tenant", "ghost"]
        )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_health_operator_shows_db_llm(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch(
            "astra.config.loader.ConfigLoader.load_tenants_from_db",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
    ):
        result = _runner().invoke(main, ["--config-dir", str(config_dir), "health"])
    assert result.exit_code in (0, 2)
    assert "Operator" in result.output
    assert "LLM" in result.output


# ── distribute ────────────────────────────────────────────────────────────────


def test_distribute_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    mock_tenants_repo = MagicMock()
    mock_tenants_repo.get = AsyncMock(return_value=None)

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch("astra.db.repos.TenantsRepo", return_value=mock_tenants_repo),
    ):
        result = _runner().invoke(
            main,
            ["--config-dir", str(config_dir), "distribute", "--tenant", "ghost", "--wp-post-id", "1"],
        )
    assert result.exit_code == 1


def test_distribute_runs_distribution(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    mock_event = MagicMock()
    mock_event.id = 7
    mock_event.tenant_id = "acme"
    mock_event.source_name = "wordpress"
    mock_event.source_post_id = "42"
    mock_event.title = "Test Post"
    mock_event.url = "https://blog.acme.com/test"
    mock_event.excerpt = "excerpt"
    from datetime import UTC, datetime
    mock_event.published_at = datetime(2026, 1, 1, tzinfo=UTC)

    mock_events_repo = MagicMock()
    mock_events_repo.get_by_source_id = AsyncMock(return_value=mock_event)

    mock_dist_repo = MagicMock()
    mock_dist_repo.get = AsyncMock(return_value=None)

    mock_tenants_repo = MagicMock()
    mock_tenants_repo.get = AsyncMock(return_value=MagicMock())

    loaded_tenant = _mock_loaded_tenant("acme")

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch("astra.db.repos.PublishEventsRepo", return_value=mock_events_repo),
        patch("astra.db.repos.DistributionRecordsRepo", return_value=mock_dist_repo),
        patch("astra.db.repos.TenantsRepo", return_value=mock_tenants_repo),
        patch(
            "astra.config.loader.ConfigLoader.load_tenants_from_db",
            new_callable=AsyncMock,
            return_value={"acme": loaded_tenant},
        ),
        patch("astra.daemon.distributor._distribute_to", new_callable=AsyncMock),
        patch("astra.llm.factory.build_llm_client"),
        patch("astra.prompts.resolver.PromptResolver"),
    ):
        result = _runner().invoke(
            main,
            [
                "--config-dir",
                str(config_dir),
                "distribute",
                "--tenant",
                "acme",
                "--wp-post-id",
                "42",
                "--platform",
                "linkedin",
            ],
        )

    assert result.exit_code == 0
    assert "Distributed to linkedin" in result.output


# ── cadence run ───────────────────────────────────────────────────────────────


def test_cadence_run_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch(
            "astra.config.loader.ConfigLoader.load_tenants_from_db",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = _runner().invoke(
            main,
            ["--config-dir", str(config_dir), "cadence", "run", "--tenant", "ghost", "--name", "x"],
        )
    assert result.exit_code == 1


def test_cadence_run_unknown_cadence_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch(
            "astra.config.loader.ConfigLoader.load_tenants_from_db",
            new_callable=AsyncMock,
            return_value={"acme": _mock_loaded_tenant("acme")},
        ),
    ):
        result = _runner().invoke(
            main,
            ["--config-dir", str(config_dir), "cadence", "run", "--tenant", "acme", "--name", "nope"],
        )
    assert result.exit_code == 1


# ── auth (unit surface check) ─────────────────────────────────────────────────


def test_auth_linkedin_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    mock_tenants_repo = MagicMock()
    mock_tenants_repo.get = AsyncMock(return_value=None)

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch("astra.db.repos.TenantsRepo", return_value=mock_tenants_repo),
    ):
        result = _runner().invoke(
            main,
            [
                "--config-dir",
                str(config_dir),
                "auth",
                "linkedin",
                "--tenant",
                "ghost",
                "--client-id",
                "cid",
                "--client-secret",
                "sec",
            ],
        )
    assert result.exit_code == 1


# ── events ────────────────────────────────────────────────────────────────────


def test_events_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    mock_tenants_repo = MagicMock()
    mock_tenants_repo.get = AsyncMock(return_value=None)

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch("astra.db.repos.TenantsRepo", return_value=mock_tenants_repo),
    ):
        result = _runner().invoke(
            main, ["--config-dir", str(config_dir), "events", "--tenant", "ghost"]
        )
    assert result.exit_code == 1


# ── tweets ────────────────────────────────────────────────────────────────────


def test_tweets_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock()

    mock_tenants_repo = MagicMock()
    mock_tenants_repo.get = AsyncMock(return_value=None)

    with (
        patch("astra.db.Database", return_value=mock_db),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch("astra.db.repos.TenantsRepo", return_value=mock_tenants_repo),
    ):
        result = _runner().invoke(
            main, ["--config-dir", str(config_dir), "tweets", "--tenant", "ghost"]
        )
    assert result.exit_code == 1
