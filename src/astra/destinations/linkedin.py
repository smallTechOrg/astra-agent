"""LinkedIn organization page destination.

Per spec/product/04-capabilities/linkedin-distribution.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from astra.db.repos import DestinationStateRepo, DistributionRecordsRepo
from astra.destinations.base import Destination
from astra.domain import (
    HealthStatus,
    PublishFailure,
    PublishResult,
    PublishSkipped,
    PublishSuccess,
    health_ok,
    health_reauth,
)
from astra.logging import get_logger

if TYPE_CHECKING:
    from astra.config.models import TenantConfig
    from astra.db.connection import Database
    from astra.domain import PublishEvent

_LINKEDIN_API = "https://api.linkedin.com/rest/posts"
_LINKEDIN_VERSION = "202401"
log = get_logger(__name__)


class LinkedInOrgDestination(Destination):
    async def publish(
        self,
        tenant: TenantConfig,
        event: PublishEvent,
        copy: str,
        db: Database,
        *,
        access_token: str,
    ) -> PublishResult:
        bound = log.bind(tenant_id=tenant.id, publish_event_id=event.db_id)

        dest_state_repo = DestinationStateRepo(db)
        dist_repo = DistributionRecordsRepo(db)

        # P4: check needs_reauth before attempting.
        state = await dest_state_repo.get(tenant.id, "linkedin")
        if state is not None and state.needs_reauth:
            return PublishSkipped(reason="needs_reauth")

        assert event.db_id is not None
        claimed = await dist_repo.claim_pending(
            tenant_id=tenant.id,
            publish_event_id=event.db_id,
            platform="linkedin",
        )
        if claimed is None:
            return PublishSkipped(reason="already_claimed")

        bound.info("linkedin_distribution_started")

        li_cfg = tenant.destinations.linkedin
        assert li_cfg is not None
        org_id = li_cfg.organization_id

        body = {
            "author": f"urn:li:organization:{org_id}",
            "commentary": copy,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "content": {
                "article": {
                    "source": event.url,
                    "title": event.title,
                    "description": event.excerpt or "",
                }
            },
            "lifecycleState": "PUBLISHED",
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": _LINKEDIN_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(_LINKEDIN_API, headers=headers, json=body)

        if resp.status_code == 201:
            platform_post_id = resp.headers.get("x-restli-id", "")
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="linkedin",
                status="sent",
                platform_post_id=platform_post_id,
                copy=copy,
            )
            bound.info("linkedin_distribution_sent", platform_post_id=platform_post_id)
            return PublishSuccess(platform_post_id=platform_post_id, copy=copy)

        error_body = resp.text[:500]

        if resp.status_code in (401, 403):
            await dest_state_repo.update(tenant.id, "linkedin", needs_reauth=True)
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="linkedin",
                status="failed",
                error=f"auth_{resp.status_code}",
            )
            bound.warning("linkedin_auth_expired", status=resp.status_code)
            return PublishFailure(error=f"auth_{resp.status_code}", transient=False)

        if resp.status_code == 422:
            await dist_repo.complete(
                tenant_id=tenant.id,
                publish_event_id=event.db_id,
                platform="linkedin",
                status="failed",
                error=f"validation_422: {error_body}",
            )
            bound.error("linkedin_distribution_failed", status=422, body=error_body)
            return PublishFailure(error="validation_422", transient=False)

        # 429, 5xx — transient; next sweep retries.
        await dist_repo.complete(
            tenant_id=tenant.id,
            publish_event_id=event.db_id,
            platform="linkedin",
            status="failed",
            error=f"http_{resp.status_code}",
        )
        bound.warning(
            "linkedin_distribution_failed",
            status=resp.status_code,
            body=error_body,
        )
        return PublishFailure(
            error=f"http_{resp.status_code}",
            transient=resp.status_code in (429,) or resp.status_code >= 500,
        )

    async def health_check(
        self,
        tenant: TenantConfig,
        *,
        access_token: str,
    ) -> HealthStatus:
        li_cfg = tenant.destinations.linkedin
        assert li_cfg is not None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": _LINKEDIN_VERSION,
        }
        url = f"https://api.linkedin.com/rest/organizations/{li_cfg.organization_id}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException):
            return HealthStatus(ok=False, reason="unreachable")

        if resp.status_code == 200:
            return health_ok()
        if resp.status_code in (401, 403):
            return health_reauth(f"http_{resp.status_code}")
        return HealthStatus(ok=False, reason=f"http_{resp.status_code}")
