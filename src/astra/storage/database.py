from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import aiosqlite
import structlog

from astra.storage.models import (
    ActionType,
    InteractionRecord,
    PostRecord,
    PostStatus,
    ShareStatus,
)

logger = structlog.get_logger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wp_post_id      INTEGER UNIQUE,
    title           TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'draft',
    shared_twitter  TEXT    NOT NULL DEFAULT 'pending',
    shared_linkedin TEXT    NOT NULL DEFAULT 'pending',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id    TEXT    NOT NULL,
    action_type TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_interaction
    ON interactions (tweet_id, action_type);
"""


class Database:
    """Async SQLite database manager.

    Usage::

        async with Database("data/astra.db") as db:
            await db.record_post(title="My Post", wp_post_id=42)
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    # ── Context manager ──────────────────────────────────────────

    async def __aenter__(self) -> Database:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        await self.init_db()
        logger.info("database_connected", path=str(self._path))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("database_closed")

    # ── Helpers ──────────────────────────────────────────────────

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            msg = "Database is not connected. Use 'async with Database(...)' as context manager."
            raise RuntimeError(msg)
        return self._conn

    # ── Schema ───────────────────────────────────────────────────

    async def init_db(self) -> None:
        """Create tables and indices if they do not exist."""
        await self.conn.executescript(_SCHEMA)
        await self.conn.commit()
        logger.debug("schema_initialized")

    # ── Posts ─────────────────────────────────────────────────────

    async def record_post(
        self,
        title: str,
        wp_post_id: int | None = None,
        status: PostStatus = PostStatus.DRAFT,
    ) -> PostRecord:
        """Insert a new post and return the created record."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        cursor = await self.conn.execute(
            """
            INSERT INTO posts (wp_post_id, title, status, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (wp_post_id, title, status.value, now),
        )
        await self.conn.commit()
        row_id = cursor.lastrowid
        return PostRecord(
            id=row_id,  # type: ignore[arg-type]
            wp_post_id=wp_post_id,
            title=title,
            status=status,
            created_at=datetime.fromisoformat(now),
        )

    async def get_post_by_wp_id(self, wp_post_id: int) -> PostRecord | None:
        """Look up a post by its WordPress post ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM posts WHERE wp_post_id = ?",
            (wp_post_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_post(row)

    async def mark_shared(
        self,
        post_id: int,
        platform: str,
        status: ShareStatus = ShareStatus.SHARED,
    ) -> None:
        """Update the share status for a post on the given platform.

        Parameters
        ----------
        post_id:
            Primary key of the post.
        platform:
            ``"twitter"`` or ``"linkedin"``.
        status:
            New share status value.
        """
        column = f"shared_{platform}"
        if column not in ("shared_twitter", "shared_linkedin"):
            msg = f"Invalid platform: {platform!r}. Must be 'twitter' or 'linkedin'."
            raise ValueError(msg)

        await self.conn.execute(
            f"UPDATE posts SET {column} = ? WHERE id = ?",  # noqa: S608
            (status.value, post_id),
        )
        await self.conn.commit()
        logger.info("post_marked_shared", post_id=post_id, platform=platform, status=status.value)

    # ── Interactions ─────────────────────────────────────────────

    async def record_interaction(
        self,
        tweet_id: str,
        action_type: ActionType,
    ) -> InteractionRecord:
        """Record a Twitter interaction (idempotent via unique index)."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        cursor = await self.conn.execute(
            """
            INSERT INTO interactions (tweet_id, action_type, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT (tweet_id, action_type) DO NOTHING
            """,
            (tweet_id, action_type.value, now),
        )
        await self.conn.commit()
        return InteractionRecord(
            id=cursor.lastrowid,  # type: ignore[arg-type]
            tweet_id=tweet_id,
            action_type=action_type,
            created_at=datetime.fromisoformat(now),
        )

    async def has_interacted(self, tweet_id: str, action_type: ActionType) -> bool:
        """Check whether the bot already performed *action_type* on *tweet_id*."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM interactions WHERE tweet_id = ? AND action_type = ?",
            (tweet_id, action_type.value),
        )
        return (await cursor.fetchone()) is not None

    async def get_pending_posts(self) -> list[PostRecord]:
        """Return all posts that still need sharing on at least one platform."""
        cursor = await self.conn.execute(
            "SELECT * FROM posts WHERE shared_twitter = 'pending' OR shared_linkedin = 'pending'"
        )
        rows = await cursor.fetchall()
        return [_row_to_post(row) for row in rows]


# ── Internal helpers ─────────────────────────────────────────────


def _row_to_post(row: sqlite3.Row) -> PostRecord:
    return PostRecord(
        id=row["id"],
        wp_post_id=row["wp_post_id"],
        title=row["title"],
        status=PostStatus(row["status"]),
        shared_twitter=ShareStatus(row["shared_twitter"]),
        shared_linkedin=ShareStatus(row["shared_linkedin"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
