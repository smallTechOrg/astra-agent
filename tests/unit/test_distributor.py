from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from astra.social.distributor import SocialDistributor
from astra.storage.database import Database
from astra.storage.models import ShareStatus
from tests.conftest import MockLLMClient


@pytest.fixture()
async def db(tmp_path: Path) -> Database:
    async with Database(tmp_path / "dist_test.db") as db:
        yield db


class TestDistributePost:
    async def test_distribute_to_twitter_and_linkedin(self, db: Database) -> None:
        mock_llm = MockLLMClient(text_response="Check out this post! #blog")
        mock_twitter = AsyncMock()
        mock_twitter.post_tweet = AsyncMock()
        mock_linkedin = AsyncMock()
        mock_linkedin.share_post = AsyncMock()

        dist = SocialDistributor(
            llm=mock_llm, twitter=mock_twitter, linkedin=mock_linkedin, db=db
        )

        record = await db.record_post(title="Test Post", wp_post_id=1)
        results = await dist.distribute_post(
            title="Test Post",
            excerpt="A test excerpt",
            url="https://blog.test/post-1",
            post_db_id=record.id,
        )

        assert results["twitter"] is True
        assert results["linkedin"] is True
        mock_twitter.post_tweet.assert_called_once()
        mock_linkedin.share_post.assert_called_once()

    async def test_no_platforms_configured(self, db: Database) -> None:
        mock_llm = MockLLMClient()
        dist = SocialDistributor(llm=mock_llm, twitter=None, linkedin=None, db=db)

        record = await db.record_post(title="Test Post", wp_post_id=2)
        results = await dist.distribute_post(
            title="Test",
            excerpt="Excerpt",
            url="https://blog.test/post-2",
            post_db_id=record.id,
        )

        assert results == {}

    async def test_twitter_failure_does_not_block_linkedin(self, db: Database) -> None:
        mock_llm = MockLLMClient(text_response="Share text")
        mock_twitter = AsyncMock()
        mock_twitter.post_tweet = AsyncMock(side_effect=RuntimeError("API down"))
        mock_linkedin = AsyncMock()
        mock_linkedin.share_post = AsyncMock()

        dist = SocialDistributor(
            llm=mock_llm, twitter=mock_twitter, linkedin=mock_linkedin, db=db
        )

        record = await db.record_post(title="Test", wp_post_id=3)
        results = await dist.distribute_post(
            title="Test",
            excerpt="Excerpt",
            url="https://blog.test/p3",
            post_db_id=record.id,
        )

        # Twitter failed but LinkedIn should succeed
        assert results["twitter"] is False
        assert results["linkedin"] is True

    async def test_marks_share_status_in_db(self, db: Database) -> None:
        mock_llm = MockLLMClient(text_response="Tweet text")
        mock_twitter = AsyncMock()
        mock_twitter.post_tweet = AsyncMock()

        dist = SocialDistributor(llm=mock_llm, twitter=mock_twitter, linkedin=None, db=db)

        record = await db.record_post(title="Shared", wp_post_id=4)
        await dist.distribute_post(
            title="Shared",
            excerpt="Excerpt",
            url="https://blog.test/p4",
            post_db_id=record.id,
        )

        found = await db.get_post_by_wp_id(4)
        assert found is not None
        assert found.shared_twitter == ShareStatus.SHARED
