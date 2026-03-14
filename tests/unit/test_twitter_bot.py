from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from astra.config import TwitterBotConfig
from astra.storage.database import Database
from astra.storage.models import ActionType
from astra.twitter.bot import TwitterBot
from astra.twitter.models import SearchResult, Tweet, TwitterUser
from tests.conftest import MockLLMClient


@pytest.fixture()
async def db(tmp_path: Path) -> Database:
    async with Database(tmp_path / "bot_test.db") as db:
        yield db


def _make_tweet(tweet_id: str = "t1", text: str = "Hello", author_id: str = "a1") -> Tweet:
    return Tweet(id=tweet_id, text=text, author_id=author_id, author_username="testuser")


@pytest.fixture()
def bot_config() -> TwitterBotConfig:
    return TwitterBotConfig(
        enabled=True,
        search_keywords=["python"],
        max_interactions_per_run=5,
        cooldown_seconds=0,  # no delay in tests
    )


class TestTwitterBot:
    async def test_disabled_bot_returns_zeros(self, db: Database) -> None:
        config = TwitterBotConfig(enabled=False)
        mock_twitter = AsyncMock()
        mock_llm = MockLLMClient()

        bot = TwitterBot(twitter=mock_twitter, llm=mock_llm, db=db, config=config)
        stats = await bot.run()

        assert stats == {"likes": 0, "replies": 0, "follows": 0}

    async def test_bot_likes_and_follows(self, db: Database, bot_config: TwitterBotConfig) -> None:
        tweet = _make_tweet("t1", "Great Python article!", "author_1")

        mock_twitter = AsyncMock()
        mock_twitter.search_recent = AsyncMock(
            return_value=SearchResult(tweets=[tweet])
        )
        mock_twitter.like_tweet = AsyncMock(return_value=True)
        mock_twitter.follow_user = AsyncMock(return_value=True)
        mock_twitter.post_tweet = AsyncMock(
            return_value=Tweet(id="reply_1", text="Nice!", author_id="me")
        )
        mock_twitter.get_user = AsyncMock(
            return_value=TwitterUser(
                id="author_1", name="Author", username="testuser", description="Python dev"
            )
        )

        mock_llm = MockLLMClient(text_response="Great point about Python!")

        bot = TwitterBot(twitter=mock_twitter, llm=mock_llm, db=db, config=bot_config)
        stats = await bot.run()

        assert stats["likes"] == 1
        assert stats["follows"] == 1
        assert stats["replies"] == 1
        mock_twitter.like_tweet.assert_called_once_with("t1")
        mock_twitter.follow_user.assert_called_once_with("author_1")

    async def test_bot_skips_already_interacted(
        self, db: Database, bot_config: TwitterBotConfig
    ) -> None:
        # Pre-record interactions
        await db.record_interaction("t2", ActionType.LIKE)
        await db.record_interaction("t2", ActionType.REPLY)
        await db.record_interaction("author_2", ActionType.FOLLOW)

        tweet = _make_tweet("t2", "Old tweet", "author_2")

        mock_twitter = AsyncMock()
        mock_twitter.search_recent = AsyncMock(
            return_value=SearchResult(tweets=[tweet])
        )
        mock_llm = MockLLMClient()

        bot = TwitterBot(twitter=mock_twitter, llm=mock_llm, db=db, config=bot_config)
        stats = await bot.run()

        # All interactions already done, so no new ones
        assert stats["likes"] == 0
        assert stats["follows"] == 0
        assert stats["replies"] == 0

    async def test_bot_respects_max_interactions(
        self, db: Database
    ) -> None:
        config = TwitterBotConfig(
            enabled=True,
            search_keywords=["python"],
            max_interactions_per_run=2,
            cooldown_seconds=0,
        )
        tweets = [_make_tweet(f"t{i}", f"Tweet {i}", f"a{i}") for i in range(10)]

        mock_twitter = AsyncMock()
        mock_twitter.search_recent = AsyncMock(
            return_value=SearchResult(tweets=tweets)
        )
        mock_twitter.like_tweet = AsyncMock(return_value=True)
        mock_twitter.follow_user = AsyncMock(return_value=True)
        mock_twitter.post_tweet = AsyncMock(
            return_value=Tweet(id="r", text="reply", author_id="me")
        )
        mock_twitter.get_user = AsyncMock(
            return_value=TwitterUser(id="a0", name="A", username="u", description="d")
        )

        mock_llm = MockLLMClient(text_response="Nice!")

        bot = TwitterBot(twitter=mock_twitter, llm=mock_llm, db=db, config=config)
        stats = await bot.run()

        total = stats["likes"] + stats["follows"] + stats["replies"]
        # Bot processes all actions for a single tweet atomically,
        # then checks the limit. So with limit=2, it processes one tweet
        # (3 actions: like+follow+reply) then stops.
        assert total <= 3  # at most one tweet fully processed
