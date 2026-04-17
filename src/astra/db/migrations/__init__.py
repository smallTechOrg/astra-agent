"""Forward-only schema migrations.

Per spec/product/07-data-model.md#migrations: single `schema_version`
table, one row, migrations numbered, applied on daemon startup before any
other DB access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.db.migrations._001_initial import SQL as _001_SQL

if TYPE_CHECKING:
    from astra.db.connection import Database

_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema", _001_SQL),
]

CURRENT_SCHEMA_VERSION = max(version for version, _, _ in _MIGRATIONS)


async def migrate(db: Database) -> int:
    """Apply every migration newer than the current schema_version.

    Returns the resulting schema version. Idempotent: calling on a
    populated DB at the current version is a no-op.
    """

    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER NOT NULL PRIMARY KEY)"
    )
    row = await db.fetch_one("SELECT version FROM schema_version LIMIT 1")
    current = int(row["version"]) if row is not None else 0

    for version, _name, sql in _MIGRATIONS:
        if version <= current:
            continue
        async for conn in db.iter_writes():
            await conn.executescript(sql)
            await conn.execute("DELETE FROM schema_version")
            await conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
        current = version

    return current


__all__ = ["CURRENT_SCHEMA_VERSION", "migrate"]
