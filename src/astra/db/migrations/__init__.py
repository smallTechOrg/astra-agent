"""Forward-only schema migrations.

Per spec/product/07-data-model.md#migrations: schema_migrations table
records applied migration IDs. Every process that opens a DB connection
runs this on startup. Idempotent: re-running against a migrated DB is safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.db.migrations._001_initial import SQL as _001_SQL
from astra.db.migrations._002_prompts import SQL as _002_SQL

if TYPE_CHECKING:
    from astra.db.connection import Database

_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial_schema", _001_SQL),
    (2, "prompts_table_and_seeds", _002_SQL),
]

CURRENT_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


async def migrate(db: Database) -> int:
    """Apply every unapplied migration in order. Returns the final migration ID."""

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    for migration_id, name, sql in _MIGRATIONS:
        exists = await db.fetch_one(
            "SELECT id FROM schema_migrations WHERE id = $1", migration_id
        )
        if exists is not None:
            continue
        async with db.pool.acquire() as conn, conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (id, name) VALUES ($1, $2)",
                migration_id,
                name,
            )

    return CURRENT_SCHEMA_VERSION


__all__ = ["CURRENT_SCHEMA_VERSION", "migrate"]
