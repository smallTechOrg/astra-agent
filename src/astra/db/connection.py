"""asyncpg connection pool.

Per spec/product/07-data-model.md: PostgreSQL via asyncpg.
DATABASE_URL configured in config/.env.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType


class Database:
    """Thin wrapper around an asyncpg connection pool.

    PostgreSQL handles concurrent reads and writes natively, so no
    write-serialization lock is needed here.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(self._dsn)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database not connected. Call .connect() first.")
        return self._pool

    async def execute(self, sql: str, *args: object) -> None:
        await self.pool.execute(sql, *args)

    async def executemany(self, sql: str, args_seq: Sequence[Sequence[object]]) -> None:
        await self.pool.executemany(sql, args_seq)

    async def fetch_one(self, sql: str, *args: object) -> asyncpg.Record | None:
        return await self.pool.fetchrow(sql, *args)

    async def fetch_all(self, sql: str, *args: object) -> list[asyncpg.Record]:
        return list(await self.pool.fetch(sql, *args))

    async def fetch_val(self, sql: str, *args: object) -> object:
        return await self.pool.fetchval(sql, *args)

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
