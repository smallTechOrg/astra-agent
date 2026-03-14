from __future__ import annotations

import asyncio

import structlog

from astra.config import TwitterBotConfig
from astra.llm.base import LLMClient
from astra.llm.prompts import TWITTER_BOT_REPLY_PROMPT
from astra.storage.database import Database
from astra.storage.models import ActionType
from astra.twitter.client import TwitterClient
from astra.twitter.models import Tweet

logger = structlog.get_logger(__name__)


class TwitterBot:
    """Autonomous Twitter engagement bot.

    Searches for tweets matching configured keywords, then likes, follows,
    and/or replies using an LLM-generated response.  All interactions are
    recorded in the database to ensure idempotency.

    Usage::

        bot = TwitterBot(twitter, llm, db, config)
        stats = await bot.run()
    """

    def __init__(
        self,
        twitter: TwitterClient,
        llm: LLMClient,
        db: Database,
        config: TwitterBotConfig,
        *,
        personality: str = (
            "You are a friendly and knowledgeable content creator who loves "
            "sharing insights about blogging, WordPress, and digital marketing."
        ),
    ) -> None:
        self._twitter = twitter
        self._llm = llm
        self._db = db
        self._config = config
        self._personality = personality
        self._log = logger.bind(component="twitter_bot")

    async def run(self) -> dict[str, int]:
        """Execute a single engagement run.

        Returns
        -------
        dict[str, int]
            Counts of actions taken: ``{"likes": N, "replies": N, "follows": N}``.
        """
        if not self._config.enabled:
            self._log.info("twitter_bot.disabled")
            return {"likes": 0, "replies": 0, "follows": 0}

        stats = {"likes": 0, "replies": 0, "follows": 0}
        interactions_done = 0

        for keyword in self._config.search_keywords:
            if interactions_done >= self._config.max_interactions_per_run:
                break

            self._log.info("twitter_bot.searching", keyword=keyword)
            try:
                result = await self._twitter.search_recent(keyword, max_results=10)
            except Exception:
                self._log.exception("twitter_bot.search_failed", keyword=keyword)
                continue

            for tweet in result.tweets:
                if interactions_done >= self._config.max_interactions_per_run:
                    break

                tweet_stats = await self._engage_tweet(tweet)
                for key in stats:
                    stats[key] += tweet_stats.get(key, 0)
                interactions_done += sum(tweet_stats.values())

                if self._config.cooldown_seconds > 0:
                    await asyncio.sleep(self._config.cooldown_seconds)

        self._log.info("twitter_bot.run_complete", stats=stats)
        return stats

    async def _engage_tweet(self, tweet: Tweet) -> dict[str, int]:
        """Engage with a single tweet: like, follow author, and reply."""
        stats: dict[str, int] = {"likes": 0, "replies": 0, "follows": 0}

        # Like
        if not await self._db.has_interacted(tweet.id, ActionType.LIKE):
            try:
                await self._twitter.like_tweet(tweet.id)
                await self._db.record_interaction(tweet.id, ActionType.LIKE)
                stats["likes"] += 1
                self._log.info("twitter_bot.liked", tweet_id=tweet.id)
            except Exception:
                self._log.exception("twitter_bot.like_failed", tweet_id=tweet.id)

        # Follow the author
        if tweet.author_id and not await self._db.has_interacted(
            tweet.author_id, ActionType.FOLLOW
        ):
            try:
                await self._twitter.follow_user(tweet.author_id)
                await self._db.record_interaction(tweet.author_id, ActionType.FOLLOW)
                stats["follows"] += 1
                self._log.info("twitter_bot.followed", author_id=tweet.author_id)
            except Exception:
                self._log.exception(
                    "twitter_bot.follow_failed", author_id=tweet.author_id
                )

        # Reply with LLM-generated content
        if not await self._db.has_interacted(tweet.id, ActionType.REPLY):
            try:
                reply_text = await self._generate_reply(tweet)
                if reply_text:
                    await self._twitter.post_tweet(reply_text, reply_to=tweet.id)
                    await self._db.record_interaction(tweet.id, ActionType.REPLY)
                    stats["replies"] += 1
                    self._log.info(
                        "twitter_bot.replied", tweet_id=tweet.id, length=len(reply_text)
                    )
            except Exception:
                self._log.exception("twitter_bot.reply_failed", tweet_id=tweet.id)

        return stats

    async def _generate_reply(self, tweet: Tweet) -> str | None:
        """Generate an LLM-powered reply to a tweet."""
        author_bio = ""
        if tweet.author_username:
            try:
                user = await self._twitter.get_user(tweet.author_username)
                author_bio = user.description or ""
            except Exception:
                self._log.debug(
                    "twitter_bot.author_lookup_failed",
                    username=tweet.author_username,
                )

        prompt = TWITTER_BOT_REPLY_PROMPT.format(
            personality=self._personality,
            original_tweet=tweet.text,
            author_bio=author_bio or "Unknown",
        )

        try:
            reply = await self._llm.generate_content(
                prompt=prompt,
                temperature=0.9,
                max_tokens=300,
            )
            reply = reply.strip().strip('"')
            if len(reply) > 280:
                reply = reply[:277] + "..."
            return reply
        except Exception:
            self._log.exception("twitter_bot.generate_reply_failed")
            return None
