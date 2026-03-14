from __future__ import annotations

from pathlib import Path

import pytest

from astra.storage.database import Database
from astra.storage.models import ActionType, PostStatus, ShareStatus


class TestInitDb:
    """Test that init_db creates tables correctly."""

    async def test_creates_posts_table(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            cursor = await db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='posts'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["name"] == "posts"

    async def test_creates_interactions_table(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            cursor = await db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='interactions'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["name"] == "interactions"

    async def test_creates_unique_index_on_interactions(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            cursor = await db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='uix_interaction'"
            )
            row = await cursor.fetchone()
            assert row is not None

    async def test_init_db_is_idempotent(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            # Calling init_db a second time should not raise
            await db.init_db()
            cursor = await db.conn.execute(
                "SELECT count(*) as cnt FROM sqlite_master WHERE type='table'"
            )
            row = await cursor.fetchone()
            assert row["cnt"] >= 2

    async def test_conn_raises_when_not_connected(self, tmp_db_path: Path) -> None:
        db = Database(tmp_db_path)
        with pytest.raises(RuntimeError, match="not connected"):
            _ = db.conn


class TestRecordPost:
    """Test inserting and retrieving post records."""

    async def test_record_post_returns_post_record(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(title="Hello World", wp_post_id=42)
            assert record.id is not None
            assert record.title == "Hello World"
            assert record.wp_post_id == 42
            assert record.status == PostStatus.DRAFT

    async def test_record_post_with_published_status(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(
                title="Published Post",
                wp_post_id=99,
                status=PostStatus.PUBLISHED,
            )
            assert record.status == PostStatus.PUBLISHED

    async def test_record_post_without_wp_id(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(title="Draft Only")
            assert record.wp_post_id is None
            assert record.title == "Draft Only"

    async def test_get_post_by_wp_id(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            await db.record_post(title="Find Me", wp_post_id=101)
            found = await db.get_post_by_wp_id(101)
            assert found is not None
            assert found.title == "Find Me"
            assert found.wp_post_id == 101

    async def test_get_post_by_wp_id_returns_none_for_missing(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            found = await db.get_post_by_wp_id(999)
            assert found is None

    async def test_multiple_posts_have_distinct_ids(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            r1 = await db.record_post(title="Post A", wp_post_id=1)
            r2 = await db.record_post(title="Post B", wp_post_id=2)
            assert r1.id != r2.id


class TestMarkShared:
    """Test updating share status for posts."""

    async def test_mark_shared_twitter(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(title="Share Me", wp_post_id=10)
            await db.mark_shared(record.id, "twitter", ShareStatus.SHARED)

            found = await db.get_post_by_wp_id(10)
            assert found is not None
            assert found.shared_twitter == ShareStatus.SHARED
            # LinkedIn should remain pending
            assert found.shared_linkedin == ShareStatus.PENDING

    async def test_mark_shared_linkedin(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(title="Share LinkedIn", wp_post_id=11)
            await db.mark_shared(record.id, "linkedin", ShareStatus.SHARED)

            found = await db.get_post_by_wp_id(11)
            assert found is not None
            assert found.shared_linkedin == ShareStatus.SHARED
            assert found.shared_twitter == ShareStatus.PENDING

    async def test_mark_shared_failed_status(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(title="Fail Share", wp_post_id=12)
            await db.mark_shared(record.id, "twitter", ShareStatus.FAILED)

            found = await db.get_post_by_wp_id(12)
            assert found is not None
            assert found.shared_twitter == ShareStatus.FAILED

    async def test_mark_shared_invalid_platform_raises(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_post(title="Bad Platform", wp_post_id=13)
            with pytest.raises(ValueError, match="Invalid platform"):
                await db.mark_shared(record.id, "facebook", ShareStatus.SHARED)


class TestRecordInteraction:
    """Test interaction recording and idempotency."""

    async def test_record_interaction_returns_record(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            record = await db.record_interaction(
                tweet_id="tweet_001", action_type=ActionType.LIKE
            )
            assert record.tweet_id == "tweet_001"
            assert record.action_type == ActionType.LIKE

    async def test_record_interaction_idempotent(self, tmp_db_path: Path) -> None:
        """Inserting the same (tweet_id, action_type) pair twice should not raise."""
        async with Database(tmp_db_path) as db:
            r1 = await db.record_interaction(
                tweet_id="tweet_dup", action_type=ActionType.RETWEET
            )
            r2 = await db.record_interaction(
                tweet_id="tweet_dup", action_type=ActionType.RETWEET
            )
            # The second insert does ON CONFLICT DO NOTHING, so it succeeds silently
            assert r1.tweet_id == r2.tweet_id

    async def test_different_actions_on_same_tweet(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            await db.record_interaction(tweet_id="tweet_x", action_type=ActionType.LIKE)
            await db.record_interaction(tweet_id="tweet_x", action_type=ActionType.REPLY)

            assert await db.has_interacted("tweet_x", ActionType.LIKE) is True
            assert await db.has_interacted("tweet_x", ActionType.REPLY) is True


class TestHasInteracted:
    """Test the has_interacted lookup."""

    async def test_has_interacted_returns_true(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            await db.record_interaction(
                tweet_id="tweet_yes", action_type=ActionType.FOLLOW
            )
            assert await db.has_interacted("tweet_yes", ActionType.FOLLOW) is True

    async def test_has_interacted_returns_false_for_missing(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            assert await db.has_interacted("tweet_no", ActionType.LIKE) is False

    async def test_has_interacted_false_for_different_action(self, tmp_db_path: Path) -> None:
        async with Database(tmp_db_path) as db:
            await db.record_interaction(
                tweet_id="tweet_partial", action_type=ActionType.LIKE
            )
            assert await db.has_interacted("tweet_partial", ActionType.RETWEET) is False
