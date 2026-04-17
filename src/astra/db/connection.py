"""Async SQLite connection with serialized writes.

Per spec/product/02-architecture.md#process-model: single writer, many
readers, driven by a single asyncio event loop.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path
    from types import TracebackType


class Database:
    """Thin wrapper around a single aiosqlite connection.

    Writes are serialized through an asyncio.Lock because SQLite's
    default journal mode is a single-writer model. Reads don't need
    the lock — aiosqlite already serializes on the one connection.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.row_factory = aiosqlite.Row

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call .connect() first.")
        return self._conn

    async def execute(
        self, sql: str, params: tuple[object, ...] | dict[str, object] = ()
    ) -> None:
        async with self._write_lock:
            await self.conn.execute(sql, params)
            await self.conn.commit()

    async def executemany(
        self, sql: str, params_seq: list[tuple[object, ...]]
    ) -> None:
        async with self._write_lock:
            await self.conn.executemany(sql, params_seq)
            await self.conn.commit()

    async def fetch_one(
        self, sql: str, params: tuple[object, ...] | dict[str, object] = ()
    ) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetch_all(
        self, sql: str, params: tuple[object, ...] | dict[str, object] = ()
    ) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

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

    async def iter_writes(self) -> AsyncIterator[aiosqlite.Connection]:
        """Escape hatch for multi-statement writes that need the lock."""

        async with self._write_lock:
            yield self.conn
            await self.conn.commit()
