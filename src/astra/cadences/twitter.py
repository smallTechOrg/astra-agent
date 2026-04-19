"""Twitter scheduled cadence.

Per spec/product/04-capabilities/twitter-scheduled-cadence.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.cadences.base import Cadence
from astra.db.repos import DestinationStateRepo, ScheduledTweetsRepo
from astra.domain import TweetFailed, TweetResult, TweetSent, TweetSkipped
from astra.logging import get_logger

if TYPE_CHECKING:
    from astra.config.models import CadenceConfig, TenantConfig
    from astra.db.connection import Database
    from astra.llm.base import LLMClient
    from astra.prompts.resolver import PromptResolver

_MIN_TWEET_LEN = 20
_MAX_TWEET_LEN = 280

log = get_logger(__name__)


class TwitterCadence(Cadence):
    async def tick(
        self,
        tenant: TenantConfig,
        cadence_cfg: CadenceConfig,
        db: Database,
        llm: LLMClient,
        prompts: PromptResolver,
        *,
        access_token: str,
    ) -> TweetResult | None:
        bound = log.bind(tenant_id=tenant.id, cadence_name=cadence_cfg.name)

        if not cadence_cfg.enabled:
            bound.info("cadence_tweet_skipped", reason="cadence_disabled")
            await ScheduledTweetsRepo(db).insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=None,
                platform_post_id=None,
                status="skipped",
                error="cadence_disabled",
            )
            return TweetSkipped(
                cadence_name=cadence_cfg.name, reason="cadence_disabled"
            )

        bound.info("cadence_tick_started")

        dest_state = await DestinationStateRepo(db).get(tenant.id, "twitter")
        if dest_state is not None and (dest_state.needs_reauth or dest_state.degraded):
            reason = "needs_reauth" if dest_state.needs_reauth else "destination_degraded"
            bound.info("cadence_tweet_skipped", reason=reason)
            await ScheduledTweetsRepo(db).insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=None,
                platform_post_id=None,
                status="skipped",
                error=reason,
            )
            return TweetSkipped(cadence_name=cadence_cfg.name, reason=reason)

        # Build {recent_tweets} variable.
        tweets_repo = ScheduledTweetsRepo(db)
        recent = await tweets_repo.list_recent_sent(
            tenant.id,
            cadence_cfg.name,
            limit=cadence_cfg.feedback_last_n,
        )
        if recent:
            recent_lines = "\n".join(f"- {t.text}" for t in recent if t.text)
            recent_tweets_var = (
                "Recent tweets from this cadence "
                "(do not repeat these themes or phrasings):\n" + recent_lines
            )
        else:
            recent_tweets_var = "(none yet — this is the first tweet in this cadence)"

        prompt_name = f"twitter_cadence_{cadence_cfg.name}"
        try:
            rendered = await prompts.render(
                prompt_name,
                recent_tweets=recent_tweets_var,
                tenant_name=tenant.name,
            )
        except Exception as exc:
            bound.error("cadence_prompt_error", error=str(exc))
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=None,
                platform_post_id=None,
                status="failed",
                error=f"prompt_error: {exc}",
            )
            return TweetFailed(
                cadence_name=cadence_cfg.name,
                error=f"prompt_error: {exc}",
                transient=False,
            )

        system_prompt = rendered.system_prompt or ""
        user_prompt = rendered.user_prompt

        try:
            raw_text = await llm.generate_content(system_prompt, user_prompt)
        except Exception as exc:
            bound.error("cadence_llm_error", error=str(exc))
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=None,
                platform_post_id=None,
                status="failed",
                error=f"llm_error: {exc}",
            )
            return TweetFailed(
                cadence_name=cadence_cfg.name,
                error=f"llm_error: {exc}",
                transient=True,
            )

        # Post-process.
        tweet_text = raw_text.strip().strip('"').strip("'").strip()
        if len(tweet_text) > _MAX_TWEET_LEN:
            tweet_text = tweet_text[: _MAX_TWEET_LEN - 1] + "…"
        if len(tweet_text) < _MIN_TWEET_LEN:
            bound.warning("cadence_tweet_skipped", reason="llm_output_too_short")
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=tweet_text,
                platform_post_id=None,
                status="failed",
                error="llm_output_too_short",
            )
            return TweetFailed(
                cadence_name=cadence_cfg.name,
                error="llm_output_too_short",
                transient=False,
            )

        bound.info("cadence_tweet_generated", length=len(tweet_text))

        # Post to X.
        parts = access_token.split("|", 3)
        if len(parts) != 4:
            raise ValueError(
                "Twitter access_token must be 'api_key|api_secret|access_token|access_secret'"
            )
        api_key, api_secret, oauth_token, oauth_secret = parts

        from requests_oauthlib import OAuth1Session

        session = OAuth1Session(
            client_key=api_key,
            client_secret=api_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=oauth_secret,
        )
        import asyncio
        import json as _json

        loop = asyncio.get_event_loop()

        def _post() -> dict[str, object]:
            resp = session.post(
                "https://api.twitter.com/2/tweets", json={"text": tweet_text}
            )
            return {
                "status": resp.status_code,
                "body": resp.text,
                "headers": dict(resp.headers),
            }

        result = await loop.run_in_executor(None, _post)
        status: int = result["status"]  # type: ignore[assignment]
        body = str(result["body"])
        headers: dict[str, str] = result["headers"]  # type: ignore[assignment]

        if status == 201:
            try:
                tweet_id = str(_json.loads(body)["data"]["id"])
            except Exception:
                tweet_id = ""
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=tweet_text,
                platform_post_id=tweet_id,
                status="sent",
            )
            bound.info("cadence_tweet_sent", tweet_id=tweet_id)
            return TweetSent(
                cadence_name=cadence_cfg.name, tweet_id=tweet_id, text=tweet_text
            )

        # Failure paths.
        if status == 401:
            await DestinationStateRepo(db).update(
                tenant.id, "twitter", needs_reauth=True
            )
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=tweet_text,
                platform_post_id=None,
                status="failed",
                error="auth_401",
            )
            bound.warning("cadence_auth_failed")
            return TweetFailed(
                cadence_name=cadence_cfg.name, error="auth_401", transient=False
            )

        if status == 429:
            reset_at = headers.get("x-rate-limit-reset", "")
            await DestinationStateRepo(db).update(
                tenant.id, "twitter", last_error=f"rate_limited:reset={reset_at}" if reset_at else "rate_limited",
            )
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=tweet_text,
                platform_post_id=None,
                status="failed",
                error="rate_limited",
            )
            return TweetFailed(
                cadence_name=cadence_cfg.name, error="rate_limited", transient=True
            )

        if status == 403:
            await tweets_repo.insert(
                tenant_id=tenant.id,
                cadence_name=cadence_cfg.name,
                text=tweet_text,
                platform_post_id=None,
                status="failed",
                error="duplicate_content",
            )
            return TweetFailed(
                cadence_name=cadence_cfg.name,
                error="duplicate_content",
                transient=False,
            )

        await tweets_repo.insert(
            tenant_id=tenant.id,
            cadence_name=cadence_cfg.name,
            text=tweet_text,
            platform_post_id=None,
            status="failed",
            error=f"http_{status}",
        )
        bound.warning("cadence_tweet_failed", status=status, body=body[:200])
        return TweetFailed(
            cadence_name=cadence_cfg.name,
            error=f"http_{status}",
            transient=status >= 500,
        )
