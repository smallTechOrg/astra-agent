"""Migration runner tests.

Gate (reports/2026-04-17-v0.1-greenfield-implementation.md, phase 2):
- Migration runs clean on an empty DB.
- Idempotent on a populated one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astra.db import CURRENT_SCHEMA_VERSION, Database, migrate

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "astra.sqlite")
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


async def test_migrate_on_empty_db_reaches_current_version(db: Database) -> None:
    result = await migrate(db)

    assert result == CURRENT_SCHEMA_VERSION
    row = await db.fetch_one("SELECT version FROM schema_version LIMIT 1")
    assert row is not None
    assert int(row["version"]) == CURRENT_SCHEMA_VERSION


async def test_migrate_creates_all_expected_tables(db: Database) -> None:
    await migrate(db)

    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    )
    names = {row["name"] for row in rows}
    expected = {
        "tenants",
        "source_state",
        "destination_state",
        "publish_events",
        "distribution_records",
        "scheduled_tweets",
        "schema_version",
    }
    assert expected.issubset(names)


async def test_migrate_is_idempotent(db: Database) -> None:
    first = await migrate(db)
    second = await migrate(db)
    third = await migrate(db)

    assert first == second == third == CURRENT_SCHEMA_VERSION

    rows = await db.fetch_all("SELECT version FROM schema_version")
    assert len(rows) == 1


async def test_foreign_keys_enforced(db: Database) -> None:
    await migrate(db)

    # publish_events.tenant_id references tenants(id) — inserting without the
    # parent row must fail when PRAGMA foreign_keys is on.
    with pytest.raises(Exception):  # noqa: B017,PT011 — aiosqlite.IntegrityError subclass
        await db.execute(
            """
            INSERT INTO publish_events
                (tenant_id, source_name, source_post_id, title, url,
                 excerpt, published_at, detected_at)
            VALUES ('ghost', 'wp', 'p1', 't', 'u', NULL,
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
