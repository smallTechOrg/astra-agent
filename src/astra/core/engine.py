from __future__ import annotations

from types import TracebackType

import structlog
from pydantic import BaseModel

from astra.config import AstraConfig
from astra.linkedin.client import LinkedInClient
from astra.llm.base import LLMClient
from astra.llm.factory import create_llm_client
from astra.llm.prompts import BLOG_POST_SYSTEM_PROMPT, BLOG_POST_USER_PROMPT
from astra.social.distributor import SocialDistributor
from astra.storage.database import Database
from astra.twitter.client import TwitterClient
from astra.wordpress.client import WordPressClient
from astra.wordpress.models import (
    ContentBrief,
    WordPressPost,
    WordPressPostResponse,
)
from astra.wordpress.models import (
    PostStatus as WPPostStatus,
)

logger = structlog.get_logger(__name__)


# ── Structured LLM output ───────────────────────────────────────


class GeneratedPost(BaseModel):
    """Schema for the structured output returned by the LLM."""

    title: str
    content: str
    excerpt: str
    tags: list[str]


# ── Engine ───────────────────────────────────────────────────────


class AstraEngine:
    """Main orchestration engine for the Astra content pipeline.

    Manages the lifecycle of the LLM client, WordPress client, social
    media clients, and local SQLite database.  Designed to be used as
    an async context manager::

        async with AstraEngine(config) as engine:
            response = await engine.generate_post(brief)
    """

    def __init__(self, config: AstraConfig) -> None:
        self._config = config

        self._llm: LLMClient = create_llm_client(
            provider=config.llm.provider,
            api_key=config.llm.api_key,
            model=config.llm.model,
        )
        self._wp = WordPressClient(
            base_url=config.wordpress.url,
            username=config.wordpress.username,
            app_password=config.wordpress.app_password,
        )
        self._db = Database(config.database_path)

        # Social clients — only created when credentials are configured.
        self._twitter: TwitterClient | None = None
        if config.twitter.bearer_token:
            self._twitter = TwitterClient(
                api_key=config.twitter.api_key,
                api_secret=config.twitter.api_secret,
                access_token=config.twitter.access_token,
                access_secret=config.twitter.access_secret,
                bearer_token=config.twitter.bearer_token,
            )

        self._linkedin: LinkedInClient | None = None
        if config.linkedin.access_token:
            self._linkedin = LinkedInClient(
                access_token=config.linkedin.access_token,
                organization_id=config.linkedin.organization_id or None,
            )

        self._distributor = SocialDistributor(
            llm=self._llm,
            twitter=self._twitter,
            linkedin=self._linkedin,
            db=self._db,
        )
        self._log = logger.bind(engine="astra")

    # ── Lifecycle ────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialise the database and validate external API connections."""
        self._log.info("engine_starting")

        # Database
        await self._db.__aenter__()
        self._log.info("database_ready")

        # WordPress
        await self._wp.__aenter__()
        await self._wp.health_check()
        self._log.info("wordpress_healthy", url=self._config.wordpress.url)

        # Social clients
        if self._twitter is not None:
            await self._twitter.__aenter__()
            self._log.info("twitter_client_ready")
        if self._linkedin is not None:
            await self._linkedin.__aenter__()
            self._log.info("linkedin_client_ready")

        self._log.info("engine_started")

    async def shutdown(self) -> None:
        """Release resources held by the engine."""
        self._log.info("engine_shutting_down")
        if self._linkedin is not None:
            await self._linkedin.close()
        if self._twitter is not None:
            await self._twitter.close()
        await self._wp.close()
        await self._db.__aexit__(None, None, None)
        self._log.info("engine_stopped")

    # ── Async context manager ────────────────────────────────────

    async def __aenter__(self) -> AstraEngine:
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.shutdown()

    # ── Content generation ───────────────────────────────────────

    async def generate_post(
        self,
        brief: ContentBrief,
        *,
        publish: bool = False,
        dry_run: bool = False,
    ) -> WordPressPostResponse | dict:
        """Generate a blog post from a content brief.

        Parameters
        ----------
        brief:
            The high-level brief describing the desired post.
        publish:
            If ``True`` the post is published immediately; otherwise it
            is created as a draft.
        dry_run:
            If ``True`` the generated content is returned as a plain
            ``dict`` without touching WordPress or the database.

        Returns
        -------
        WordPressPostResponse | dict
            A WordPress API response on success, or a dict of the
            generated content when *dry_run* is ``True``.
        """
        self._log.info(
            "generate_post.start",
            topic=brief.topic,
            tone=brief.tone,
            word_count=brief.target_word_count,
            dry_run=dry_run,
            publish=publish,
        )

        # 1. Build the user prompt from the brief
        keywords_str = ", ".join(brief.keywords) if brief.keywords else "none"
        user_prompt = BLOG_POST_USER_PROMPT.format(
            topic=brief.topic,
            tone=brief.tone,
            word_count=brief.target_word_count,
            keywords=keywords_str,
        )

        # 2. Call LLM for structured output
        generated: GeneratedPost = await self._llm.generate_structured(
            prompt=user_prompt,
            response_model=GeneratedPost,
            system_prompt=BLOG_POST_SYSTEM_PROMPT,
        )

        self._log.info(
            "generate_post.llm_complete",
            title=generated.title,
            content_len=len(generated.content),
            tags=generated.tags,
        )

        # 3. Build the WordPressPost model
        wp_status = WPPostStatus.PUBLISH if publish else WPPostStatus.DRAFT
        wp_post = WordPressPost(
            title=generated.title,
            content=generated.content,
            excerpt=generated.excerpt,
            status=wp_status,
        )

        # 4. Dry-run: return raw data without side-effects
        if dry_run:
            self._log.info("generate_post.dry_run", title=generated.title)
            return {
                "title": generated.title,
                "content": generated.content,
                "excerpt": generated.excerpt,
                "tags": generated.tags,
                "status": wp_status.value,
            }

        # 5. Publish to WordPress
        response = await self._wp.create_post(wp_post)

        self._log.info(
            "generate_post.published",
            wp_post_id=response.id,
            link=response.link,
            status=response.status,
        )

        # 6. Record in local database
        from astra.storage.models import PostStatus

        db_status = PostStatus.PUBLISHED if publish else PostStatus.DRAFT
        await self._db.record_post(
            title=generated.title,
            wp_post_id=response.id,
            status=db_status,
        )

        self._log.info("generate_post.recorded", wp_post_id=response.id)
        return response

    # ── Social distribution ──────────────────────────────────────

    async def distribute_post(
        self,
        wp_post_id: int,
    ) -> dict[str, bool]:
        """Distribute an existing WordPress post to social platforms.

        Looks up the post in the local DB and WordPress, then delegates
        to the ``SocialDistributor``.
        """
        post_record = await self._db.get_post_by_wp_id(wp_post_id)
        if post_record is None:
            raise ValueError(f"No local record for WordPress post {wp_post_id}")

        wp_post = await self._wp.get_post(wp_post_id)
        return await self._distributor.distribute_post(
            title=post_record.title,
            excerpt=wp_post.title.rendered,
            url=wp_post.link,
            post_db_id=post_record.id,
        )
