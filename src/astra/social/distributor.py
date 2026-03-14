from __future__ import annotations

import asyncio

import structlog

from astra.linkedin.client import LinkedInClient
from astra.linkedin.models import LinkedInShare
from astra.llm.base import LLMClient
from astra.llm.prompts import SOCIAL_LINKEDIN_PROMPT, SOCIAL_TWEET_PROMPT
from astra.storage.database import Database
from astra.storage.models import ShareStatus
from astra.twitter.client import TwitterClient

logger = structlog.get_logger(__name__)


class SocialDistributor:
    """Orchestrates social media distribution across multiple platforms.

    Generates platform-specific copy via an LLM and publishes to each
    configured platform independently.  A failure on one platform does
    not prevent posting to the others.
    """

    def __init__(
        self,
        llm: LLMClient,
        twitter: TwitterClient | None,
        linkedin: LinkedInClient | None,
        db: Database,
    ) -> None:
        self._llm = llm
        self._twitter = twitter
        self._linkedin = linkedin
        self._db = db
        self._log = logger.bind(component="social_distributor")

    # ── Public API ───────────────────────────────────────────────

    async def distribute_post(
        self,
        title: str,
        excerpt: str,
        url: str,
        post_db_id: int,
    ) -> dict[str, bool]:
        """Generate platform-specific copy and distribute to all configured platforms.

        Parameters
        ----------
        title:
            The blog post title.
        excerpt:
            A short excerpt or summary of the blog post.
        url:
            The public URL of the blog post.
        post_db_id:
            The local database primary key of the post record, used to
            update share status.

        Returns
        -------
        dict[str, bool]
            A mapping of platform name to success/failure boolean.
        """
        self._log.info(
            "distribute_post.start",
            title=title,
            url=url,
            post_db_id=post_db_id,
        )

        results: dict[str, bool] = {}
        tasks: list[asyncio.Task[bool]] = []
        task_names: list[str] = []

        if self._twitter is not None:
            task = asyncio.create_task(
                self._distribute_twitter(title, excerpt, url, post_db_id),
            )
            tasks.append(task)
            task_names.append("twitter")

        if self._linkedin is not None:
            task = asyncio.create_task(
                self._distribute_linkedin(title, excerpt, url, post_db_id),
            )
            tasks.append(task)
            task_names.append("linkedin")

        if not tasks:
            self._log.warning("distribute_post.no_platforms_configured")
            return results

        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(task_names, completed, strict=True):
            if isinstance(result, BaseException):
                self._log.error(
                    "distribute_post.platform_error",
                    platform=name,
                    error=str(result),
                )
                results[name] = False
            else:
                results[name] = result

        self._log.info("distribute_post.complete", results=results)
        return results

    # ── Private helpers ──────────────────────────────────────────

    async def _distribute_twitter(
        self,
        title: str,
        excerpt: str,
        url: str,
        post_db_id: int,
    ) -> bool:
        """Generate tweet copy via LLM and post to Twitter."""
        try:
            prompt = SOCIAL_TWEET_PROMPT.format(title=title, excerpt=excerpt, url=url)
            tweet_text = await self._llm.generate_content(
                prompt=prompt,
                temperature=0.8,
                max_tokens=300,
            )
            tweet_text = tweet_text.strip()

            self._log.info(
                "distribute_twitter.generated",
                length=len(tweet_text),
                post_db_id=post_db_id,
            )

            assert self._twitter is not None  # guarded by caller
            await self._twitter.post_tweet(tweet_text)

            await self._db.mark_shared(post_db_id, "twitter", ShareStatus.SHARED)
            self._log.info("distribute_twitter.ok", post_db_id=post_db_id)
            return True

        except Exception:
            self._log.exception("distribute_twitter.failed", post_db_id=post_db_id)
            await self._db.mark_shared(post_db_id, "twitter", ShareStatus.FAILED)
            return False

    async def _distribute_linkedin(
        self,
        title: str,
        excerpt: str,
        url: str,
        post_db_id: int,
    ) -> bool:
        """Generate LinkedIn copy via LLM and post to LinkedIn."""
        try:
            prompt = SOCIAL_LINKEDIN_PROMPT.format(title=title, excerpt=excerpt, url=url)
            linkedin_text = await self._llm.generate_content(
                prompt=prompt,
                temperature=0.7,
                max_tokens=1000,
            )
            linkedin_text = linkedin_text.strip()

            self._log.info(
                "distribute_linkedin.generated",
                length=len(linkedin_text),
                post_db_id=post_db_id,
            )

            share = LinkedInShare(
                text=linkedin_text,
                url=url,
                title=title,
                description=excerpt,
            )

            assert self._linkedin is not None  # guarded by caller
            await self._linkedin.share_post(share)

            await self._db.mark_shared(post_db_id, "linkedin", ShareStatus.SHARED)
            self._log.info("distribute_linkedin.ok", post_db_id=post_db_id)
            return True

        except Exception:
            self._log.exception("distribute_linkedin.failed", post_db_id=post_db_id)
            await self._db.mark_shared(post_db_id, "linkedin", ShareStatus.FAILED)
            return False
