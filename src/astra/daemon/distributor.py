"""Distribution orchestration: fan-out new publish events to enabled destinations.

Per spec/product/04-capabilities/linkedin-distribution.md and
spec/product/04-capabilities/twitter-blog-announcement.md.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from astra.db.repos import DistributionRecordsRepo, PublishEventsRepo
from astra.destinations import get_destination
from astra.logging import get_logger

if TYPE_CHECKING:
    from pydantic import SecretStr

    from astra.config.models import TenantConfig
    from astra.db.connection import Database
    from astra.db.repos import DistributionRecord
    from astra.domain import PublishEvent
    from astra.llm.base import LLMClient
    from astra.prompts.resolver import PromptResolver

log = get_logger(__name__)


async def distribute_event(
    tenant: TenantConfig,
    publish_event_id: int,
    db: Database,
    llm: LLMClient,
    prompts: PromptResolver,
    secrets: dict[str, SecretStr],
) -> None:
    """Fan-out one publish_event to all enabled destinations concurrently."""
    repo = PublishEventsRepo(db)
    event_rec = await repo.get_by_id(publish_event_id)
    if event_rec is None:
        return

    from astra.domain import PublishEvent

    event = PublishEvent(
        tenant_id=event_rec.tenant_id,
        source_name=event_rec.source_name,
        source_post_id=event_rec.source_post_id,
        title=event_rec.title,
        url=event_rec.url,
        excerpt=event_rec.excerpt,
        published_at=event_rec.published_at,
        db_id=event_rec.id,
    )

    tasks = []
    if tenant.destinations.linkedin.enabled:
        tasks.append(_distribute_to(tenant, event, db, llm, prompts, secrets, "linkedin"))
    if tenant.destinations.twitter.enabled:
        tasks.append(_distribute_to(tenant, event, db, llm, prompts, secrets, "twitter"))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _distribute_to(
    tenant: TenantConfig,
    event: PublishEvent,
    db: Database,
    llm: LLMClient,
    prompts: PromptResolver,
    secrets: dict[str, SecretStr],
    platform: str,
) -> None:
    bound = log.bind(tenant_id=tenant.id, publish_event_id=event.db_id, platform=platform)
    try:
        copy = await _generate_copy(tenant, event, llm, prompts, platform)
        access_token = _build_access_token(tenant, secrets, platform)
        dest_cls = get_destination(platform)
        dest = dest_cls()
        result = await dest.publish(tenant, event, copy, db, access_token=access_token)
        bound.info("distribution_completed", result=type(result).__name__)
    except Exception as exc:
        bound.error("distribution_error", error=str(exc))


async def _generate_copy(
    tenant: TenantConfig,
    event: PublishEvent,
    llm: LLMClient,
    prompts: PromptResolver,
    platform: str,
) -> str:
    if platform == "linkedin":
        prompt_name = tenant.destinations.linkedin.prompt
    else:
        prompt_name = tenant.destinations.twitter.announcement_prompt

    rendered = await prompts.render(
        prompt_name,
        title=event.title,
        url=event.url,
        excerpt=event.excerpt or "",
        tenant_name=tenant.name,
    )
    system_prompt = rendered.system_prompt or ""
    return await llm.generate_content(system_prompt, rendered.user_prompt)


def _build_access_token(
    tenant: TenantConfig,
    secrets: dict[str, SecretStr],
    platform: str,
) -> str:
    def _get(key: str) -> str:
        s = secrets.get(key)
        return s.get_secret_value() if s else ""

    if platform == "linkedin":
        return _get("LINKEDIN_ACCESS_TOKEN")

    # Twitter: pack four keys as pipe-separated string (P5 — secrets passed as args)
    return "|".join([
        _get("TWITTER_API_KEY"),
        _get("TWITTER_API_SECRET"),
        _get("TWITTER_ACCESS_TOKEN"),
        _get("TWITTER_ACCESS_SECRET"),
    ])


async def sweep_pending(
    tenant: TenantConfig,
    db: Database,
    llm: LLMClient,
    prompts: PromptResolver,
    secrets: dict[str, SecretStr],
) -> None:
    """Retry transient distribution failures (the share-sweep job).

    Permanent failures (transient=False) are left alone; they require operator action
    (e.g. prompt fix, re-auth). Transient failures get a fresh distribute_event call.
    Per spec invariant 5 in 07-data-model.md.
    """
    bound = log.bind(tenant_id=tenant.id)
    retryable = await DistributionRecordsRepo(db).list_retryable(tenant.id)
    if not retryable:
        return

    bound.info("share_sweep_started", count=len(retryable))
    for rec in retryable:
        try:
            await _retry_one(tenant, rec, db, llm, prompts, secrets)
        except Exception as exc:
            bound.error("share_sweep_record_error", record_id=rec.id, error=str(exc))


async def _retry_one(
    tenant: TenantConfig,
    rec: DistributionRecord,
    db: Database,
    llm: LLMClient,
    prompts: PromptResolver,
    secrets: dict[str, SecretStr],
) -> None:
    from astra.db.repos import DistributionRecordsRepo

    dist_repo = DistributionRecordsRepo(db)
    await dist_repo.replace_on_retry(
        tenant_id=tenant.id,
        publish_event_id=rec.publish_event_id,
        platform=rec.platform,
    )
    await _distribute_to(
        tenant,
        await _load_event(rec.publish_event_id, tenant.id, db),
        db,
        llm,
        prompts,
        secrets,
        rec.platform,
    )


async def _load_event(
    publish_event_id: int, tenant_id: str, db: Database
) -> PublishEvent:
    from astra.db.repos import PublishEventsRepo
    from astra.domain import PublishEvent

    rec = await PublishEventsRepo(db).get_by_id(publish_event_id)
    if rec is None or rec.tenant_id != tenant_id:
        raise ValueError(f"publish_event {publish_event_id} not found for tenant {tenant_id!r}")
    return PublishEvent(
        tenant_id=rec.tenant_id,
        source_name=rec.source_name,
        source_post_id=rec.source_post_id,
        title=rec.title,
        url=rec.url,
        excerpt=rec.excerpt,
        published_at=rec.published_at,
        db_id=rec.id,
    )
