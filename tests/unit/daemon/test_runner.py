"""TenantRunner unit tests.

Gate (phase 9): poll_and_distribute calls source.poll and fans out events;
share_sweep delegates to sweep_pending; cadence_tick calls the cadence;
all public methods catch exceptions and never re-raise (P3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from astra.config.models import TenantConfig
from astra.daemon.runner import TenantRunner
from astra.db import Database, migrate
from astra.db.repos import TenantsRepo
from astra.domain import PublishEvent, TweetSent

if TYPE_CHECKING:
    from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────

def _tenant(tenant_id: str = "acme") -> TenantConfig:
    return TenantConfig.model_validate({
        "id": tenant_id,
        "name": "Acme Corp",
        "enabled": True,
        "source": {
            "type": "wordpress",
            "url": "https://blog.example.com",
            "username": "admin",
            "app_password_env": "WP_APP_PASSWORD",
        },
        "destinations": {
            "twitter": {"enabled": True},
        },
        "cadences": [
            {"name": "daily", "cron": "0 9 * * *", "prompt": "twitter_cadence_daily"},
        ],
    })


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "astra.sqlite")
    await database.connect()
    await migrate(database)
    await TenantsRepo(database).upsert("acme", "Acme", enabled=True)
    try:
        yield database
    finally:
        await database.close()


def _make_runner(tenant: TenantConfig, db: Database) -> TenantRunner:
    llm = AsyncMock()
    llm.generate_content = AsyncMock(return_value="copy text")
    prompts = MagicMock()
    from astra.prompts.resolver import RenderedPrompt
    prompts.render = MagicMock(return_value=RenderedPrompt(system_prompt=None, user_prompt="write"))
    return TenantRunner(
        tenant=tenant,
        db=db,
        llm=llm,
        prompts=prompts,
        secrets={},
    )


# ── poll_and_distribute ──────────────────────────────────────────

async def test_poll_and_distribute_calls_source(db: Database) -> None:
    runner = _make_runner(_tenant(), db)

    with (
        patch("astra.daemon.runner.get_source") as mock_get_source,
        patch("astra.daemon.runner.distribute_event") as mock_distribute,
    ):
        mock_source = MagicMock()
        mock_source.poll = AsyncMock(return_value=[])
        mock_get_source.return_value = lambda: mock_source
        mock_distribute.return_value = None

        await runner.poll_and_distribute()

    mock_source.poll.assert_called_once()


async def test_poll_distributes_new_events(db: Database) -> None:
    runner = _make_runner(_tenant(), db)

    event = PublishEvent(
        tenant_id="acme",
        source_name="wordpress",
        source_post_id="p1",
        title="Post",
        url="https://example.com",
        excerpt=None,
        published_at="2026-01-01T00:00:00Z",
        db_id=1,
    )

    distribute_calls: list[int] = []

    with (
        patch("astra.daemon.runner.get_source") as mock_get_source,
        patch("astra.daemon.runner.distribute_event") as mock_distribute,
    ):
        mock_source = MagicMock()
        mock_source.poll = AsyncMock(return_value=[event])
        mock_get_source.return_value = lambda: mock_source

        async def _fake_distribute(tenant, event_id, *args, **kwargs):
            distribute_calls.append(event_id)

        mock_distribute.side_effect = _fake_distribute

        await runner.poll_and_distribute()

    assert distribute_calls == [1]


async def test_poll_skips_events_with_no_db_id(db: Database) -> None:
    """Events without db_id (insert collision) are not distributed."""
    runner = _make_runner(_tenant(), db)

    event = PublishEvent(
        tenant_id="acme",
        source_name="wordpress",
        source_post_id="p1",
        title="Post",
        url="https://example.com",
        excerpt=None,
        published_at="2026-01-01T00:00:00Z",
        db_id=None,
    )

    with (
        patch("astra.daemon.runner.get_source") as mock_get_source,
        patch("astra.daemon.runner.distribute_event") as mock_distribute,
    ):
        mock_source = MagicMock()
        mock_source.poll = AsyncMock(return_value=[event])
        mock_get_source.return_value = lambda: mock_source
        mock_distribute.return_value = None

        await runner.poll_and_distribute()

    mock_distribute.assert_not_called()


# ── P3: exceptions never re-raise ────────────────────────────────

async def test_poll_source_exception_does_not_propagate(db: Database) -> None:
    """P3: a crashing source poll logs the error but doesn't raise to the scheduler."""
    runner = _make_runner(_tenant(), db)

    with patch("astra.daemon.runner.get_source") as mock_get_source:
        mock_source = MagicMock()
        mock_source.poll = AsyncMock(side_effect=RuntimeError("WP is down"))
        mock_get_source.return_value = lambda: mock_source

        # Must not raise.
        await runner.poll_and_distribute()


async def test_share_sweep_exception_does_not_propagate(db: Database) -> None:
    """P3: share_sweep catching all exceptions."""
    runner = _make_runner(_tenant(), db)

    with patch("astra.daemon.runner.sweep_pending", AsyncMock(side_effect=RuntimeError("DB error"))):
        await runner.share_sweep()


async def test_cadence_tick_exception_does_not_propagate(db: Database) -> None:
    """P3: cadence tick catching all exceptions."""
    runner = _make_runner(_tenant(), db)
    tenant = _tenant()
    cadence_cfg = tenant.cadences[0]

    with patch("astra.cadences.TwitterCadence.tick", AsyncMock(side_effect=RuntimeError("Twitter error"))):
        await runner.cadence_tick(cadence_cfg)


# ── cadence_tick ─────────────────────────────────────────────────

async def test_cadence_tick_calls_cadence(db: Database) -> None:
    runner = _make_runner(_tenant(), db)
    tenant = _tenant()
    cadence_cfg = tenant.cadences[0]
    result = TweetSent(cadence_name="daily", tweet_id="123", text="Hello!")

    with patch("astra.cadences.get_cadence") as mock_get_cadence:
        mock_cadence = MagicMock()
        mock_cadence.tick = AsyncMock(return_value=result)
        mock_get_cadence.return_value = lambda: mock_cadence

        await runner.cadence_tick(cadence_cfg)

    mock_cadence.tick.assert_called_once()
