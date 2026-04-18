"""Migration runner tests.

Gate (reports/2026-04-17-v0.1-greenfield-implementation.md, phase 2):
- Migration runs clean on an empty DB.
- Idempotent on a populated one.
"""

from __future__ import annotations

import os

import pytest

from astra.db import CURRENT_SCHEMA_VERSION, Database, migrate

TEST_DSN = os.environ.get("DATABASE_URL", "postgresql://astra:astra@localhost:5432/astra_test")


@pytest.fixture
async def fresh_db() -> Database:
    """Postgres connection with the public schema dropped and recreated."""
    database = Database(TEST_DSN)
    await database.connect()
    await database.execute("DROP SCHEMA public CASCADE")
    await database.execute("CREATE SCHEMA public")
    try:
        yield database
    finally:
        await database.close()


async def test_migrate_on_empty_db_reaches_current_version(fresh_db: Database) -> None:
    result = await migrate(fresh_db)

    assert result == CURRENT_SCHEMA_VERSION
    row = await fresh_db.fetch_one(
        "SELECT id FROM schema_migrations WHERE id = $1", CURRENT_SCHEMA_VERSION
    )
    assert row is not None


async def test_migrate_creates_all_expected_tables(fresh_db: Database) -> None:
    await migrate(fresh_db)

    rows = await fresh_db.fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )
    names = {row["table_name"] for row in rows}
    expected = {
        "tenants",
        "tenant_config",
        "tenant_secrets",
        "cadences",
        "source_state",
        "destination_state",
        "publish_events",
        "distribution_records",
        "scheduled_tweets",
        "daemon_heartbeat",
        "schema_migrations",
    }
    assert expected.issubset(names)


async def test_migrate_is_idempotent(fresh_db: Database) -> None:
    first = await migrate(fresh_db)
    second = await migrate(fresh_db)
    third = await migrate(fresh_db)

    assert first == second == third == CURRENT_SCHEMA_VERSION

    # Each migration ID appears exactly once.
    rows = await fresh_db.fetch_all("SELECT id FROM schema_migrations")
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))


async def test_foreign_keys_enforced(fresh_db: Database) -> None:
    await migrate(fresh_db)

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    # publish_events.tenant_id references tenants(id) — inserting without the
    # parent row must fail.
    import asyncpg
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await fresh_db.execute(
            """
            INSERT INTO publish_events
                (tenant_id, source_name, source_post_id, title, url,
                 excerpt, published_at, detected_at)
            VALUES ($1, $2, $3, $4, $5, NULL, $6, $6)
            """,
            "ghost-tenant", "wp", "p1", "t", "u", now,
        )
