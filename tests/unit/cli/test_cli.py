"""CLI unit tests — per spec/product/06-cli.md."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from astra.cli.main import main

if TYPE_CHECKING:
    from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _operator_yaml() -> str:
    return """\
log_level: info
database_path: astra.db
llm:
  provider: openai
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  max_tokens: 512
  temperature: 0.7
"""


def _tenant_yaml(tenant_id: str = "acme", enabled: bool = True) -> str:
    return f"""\
id: {tenant_id}
name: Acme Corp
enabled: {"true" if enabled else "false"}
source:
  type: wordpress
  url: https://blog.acme.com
  username: admin
  app_password_env: WP_APP_PASSWORD
  poll_cron: "*/5 * * * *"
destinations:
  linkedin:
    enabled: true
    organization_id: "12345"
    access_token_env: LINKEDIN_ACCESS_TOKEN
    prompt: linkedin_announcement
  twitter:
    enabled: false
cadences: []
"""


def _build_config(tmp_path: Path, *, tenant_id: str = "acme", enabled: bool = True) -> Path:
    config_dir = tmp_path / "config"
    _write(config_dir / "operator.yaml", _operator_yaml())
    _write(config_dir / ".env", "OPENAI_API_KEY=sk-test\n")
    _write(config_dir / "tenants" / tenant_id / "tenant.yaml", _tenant_yaml(tenant_id, enabled))
    _write(config_dir / "tenants" / tenant_id / ".env", "WP_APP_PASSWORD=pw\nLINKEDIN_ACCESS_TOKEN=tok\n")
    return config_dir


def _runner() -> CliRunner:
    return CliRunner()


# ── version ───────────────────────────────────────────────────────────────────


def test_version_cmd(tmp_path: Path) -> None:
    result = _runner().invoke(main, ["--config-dir", str(tmp_path / "config"), "version"])
    assert result.exit_code == 0
    assert "astra-agent" in result.output


# ── tenant add ────────────────────────────────────────────────────────────────


def test_tenant_add_creates_files(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "add", "new-co"])
    assert result.exit_code == 0
    assert (config_dir / "tenants" / "new-co" / "tenant.yaml").exists()
    assert (config_dir / "tenants" / "new-co" / ".env").exists()


def test_tenant_add_invalid_id_exits_3(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "add", "BAD_ID"])
    assert result.exit_code == 3


def test_tenant_add_duplicate_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "add", "acme"])
    assert result.exit_code == 1


# ── tenant enable / disable ───────────────────────────────────────────────────


def test_tenant_enable_writes_yaml(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path, enabled=False)
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "enable", "acme"])
    assert result.exit_code == 0
    yaml_text = (config_dir / "tenants" / "acme" / "tenant.yaml").read_text()
    assert "enabled: true" in yaml_text


def test_tenant_disable_writes_yaml(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path, enabled=True)
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "disable", "acme"])
    assert result.exit_code == 0
    yaml_text = (config_dir / "tenants" / "acme" / "tenant.yaml").read_text()
    assert "enabled: false" in yaml_text


def test_tenant_enable_unknown_exits_1(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "enable", "ghost"])
    assert result.exit_code == 1


# ── tenant list ───────────────────────────────────────────────────────────────


def test_tenant_list_shows_tenant(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "list"])
    assert result.exit_code == 0
    assert "acme" in result.output


def test_tenant_list_no_tenants(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write(config_dir / "operator.yaml", _operator_yaml())
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "tenant", "list"])
    assert result.exit_code == 0
    assert "No tenants" in result.output


# ── tenant remove ─────────────────────────────────────────────────────────────


def test_tenant_remove_force_deletes_dir(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    tenant_dir = config_dir / "tenants" / "acme"
    assert tenant_dir.exists()
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "tenant", "remove", "--force", "acme"]
    )
    assert result.exit_code == 0
    assert not tenant_dir.exists()


def test_tenant_remove_unknown_exits_1(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "tenant", "remove", "--force", "ghost"]
    )
    assert result.exit_code == 1


# ── health ────────────────────────────────────────────────────────────────────


def test_health_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "health", "--tenant", "ghost"]
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_health_operator_shows_db_llm(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(main, ["--config-dir", str(config_dir), "health"])
    assert result.exit_code in (0, 2)
    assert "Operator" in result.output
    assert "LLM" in result.output


# ── distribute ────────────────────────────────────────────────────────────────


def test_distribute_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(
        main,
        ["--config-dir", str(config_dir), "distribute", "--tenant", "ghost", "--wp-post-id", "1"],
    )
    assert result.exit_code == 1


def test_distribute_runs_distribution(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)

    mock_db = AsyncMock()
    mock_db_cls = MagicMock(return_value=mock_db)

    mock_event = MagicMock()
    mock_event.id = 7
    mock_event.tenant_id = "acme"
    mock_event.source_name = "wordpress"
    mock_event.source_post_id = "42"
    mock_event.title = "Test Post"
    mock_event.url = "https://blog.acme.com/test"
    mock_event.excerpt = "excerpt"
    mock_event.published_at = "2026-01-01T00:00:00"

    mock_events_repo = MagicMock()
    mock_events_repo.get_by_source_id = AsyncMock(return_value=mock_event)

    mock_dist_repo = MagicMock()
    mock_dist_repo.get = AsyncMock(return_value=None)

    mock_tenants_repo = MagicMock()
    mock_tenants_repo.upsert = AsyncMock()

    with (
        patch("astra.db.Database", mock_db_cls),
        patch("astra.db.migrate", new_callable=AsyncMock),
        patch("astra.db.repos.PublishEventsRepo", return_value=mock_events_repo),
        patch("astra.db.repos.DistributionRecordsRepo", return_value=mock_dist_repo),
        patch("astra.db.repos.TenantsRepo", return_value=mock_tenants_repo),
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
    result = _runner().invoke(
        main,
        ["--config-dir", str(config_dir), "cadence", "run", "--tenant", "ghost", "--name", "x"],
    )
    assert result.exit_code == 1


def test_cadence_run_unknown_cadence_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(
        main,
        ["--config-dir", str(config_dir), "cadence", "run", "--tenant", "acme", "--name", "nope"],
    )
    assert result.exit_code == 1


# ── auth (unit surface check) ─────────────────────────────────────────────────


def test_auth_linkedin_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
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
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "events", "--tenant", "ghost"]
    )
    assert result.exit_code == 1


def test_events_no_db_prints_message(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "events", "--tenant", "acme"]
    )
    assert result.exit_code == 0
    assert "No database" in result.output


# ── tweets ────────────────────────────────────────────────────────────────────


def test_tweets_unknown_tenant_exits_1(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "tweets", "--tenant", "ghost"]
    )
    assert result.exit_code == 1


def test_tweets_no_db_prints_message(tmp_path: Path) -> None:
    config_dir = _build_config(tmp_path)
    result = _runner().invoke(
        main, ["--config-dir", str(config_dir), "tweets", "--tenant", "acme"]
    )
    assert result.exit_code == 0
    assert "No database" in result.output
