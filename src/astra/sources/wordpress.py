"""WordPressSource — poll WordPress REST API for new posts.

Per spec/product/04-capabilities/wp-publish-detection.md.
"""

from __future__ import annotations

import base64
import html
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from astra.db.repos import PublishEventsRepo, SourceStateRepo
from astra.domain import PublishEvent
from astra.logging import get_logger
from astra.sources.base import Source

if TYPE_CHECKING:
    from astra.config.models import TenantConfig
    from astra.db.connection import Database

log = get_logger(__name__)

_FIRST_RUN_LOOKBACK = timedelta(days=7)
_WP_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _parse_wp_date(date_gmt: str) -> datetime:
    """Parse WordPress date_gmt (UTC, no Z suffix) → timezone-aware datetime."""
    return datetime.strptime(date_gmt, _WP_DATE_FORMAT).replace(tzinfo=UTC)


class WordPressSource(Source):
    async def poll(
        self,
        tenant: TenantConfig,
        db: Database,
        *,
        app_password: str,
    ) -> list[PublishEvent]:
        bound = log.bind(tenant_id=tenant.id)
        bound.info("publish_poll_started")

        source_cfg = tenant.source
        state_repo = SourceStateRepo(db)
        events_repo = PublishEventsRepo(db)

        state = await state_repo.get(tenant.id, "wordpress")
        if state is None or state.last_seen_at is None:
            cutoff_dt = datetime.now(UTC) - _FIRST_RUN_LOOKBACK
        else:
            cutoff_dt = state.last_seen_at

        cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"{source_cfg.url.rstrip('/')}/wp-json/wp/v2/posts"
            f"?status=publish&after={cutoff}&per_page=50&orderby=date&order=asc"
        )
        credentials = base64.b64encode(
            f"{source_cfg.username}:{app_password}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {credentials}"}

        try:
            posts = await _fetch_posts(url, headers)
        except _AuthError:
            bound.warning("wp_auth_failed")
            return []
        except _RateLimitError:
            bound.warning("wp_poll_rate_limited")
            return []
        except _BadJsonError as exc:
            bound.warning("wp_poll_bad_response", reason=str(exc))
            return []
        except Exception as exc:
            bound.warning("wp_poll_failed", reason=str(exc))
            return []

        new_events: list[PublishEvent] = []
        last_seen: datetime | None = None

        for post in posts:
            try:
                post_id = str(post["id"])
                title = html.unescape(post.get("title", {}).get("rendered", ""))
                link = str(post.get("link", ""))
                excerpt_raw = post.get("excerpt", {}).get("rendered", "")
                excerpt = html.unescape(_strip_html(excerpt_raw)) or None
                published_at = _parse_wp_date(str(post.get("date_gmt", "")))

                record = await events_repo.insert_if_new(
                    tenant_id=tenant.id,
                    source_name="wordpress",
                    source_post_id=post_id,
                    title=title,
                    url=link,
                    excerpt=excerpt,
                    published_at=published_at,
                )

                if record is not None:
                    event = PublishEvent(
                        tenant_id=tenant.id,
                        source_name="wordpress",
                        source_post_id=post_id,
                        title=title,
                        url=link,
                        excerpt=excerpt,
                        published_at=published_at,
                        db_id=record.id,
                    )
                    new_events.append(event)
                    last_seen = published_at
                    bound.info(
                        "publish_event_created",
                        source_post_id=post_id,
                        title=title,
                    )

            except Exception as exc:  # noqa: BLE001
                bound.error("publish_event_insert_error", post_id=post.get("id"), reason=str(exc))

        await state_repo.upsert(
            tenant.id,
            "wordpress",
            last_seen_at=last_seen,
            last_polled_at=datetime.now(UTC),
        )

        bound.info("publish_poll_complete", new_events_count=len(new_events))
        return new_events


# ── internal helpers ─────────────────────────────────────────────

class _AuthError(Exception):
    pass


class _RateLimitError(Exception):
    pass


class _BadJsonError(Exception):
    pass


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _fetch_posts(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
        raise exc

    if resp.status_code == 401:
        raise _AuthError("401")
    if resp.status_code == 429:
        raise _RateLimitError("429")
    if resp.status_code >= 500:
        resp.raise_for_status()

    try:
        data = resp.json()
    except Exception as exc:
        raise _BadJsonError(str(exc)) from exc

    if not isinstance(data, list):
        raise _BadJsonError(f"expected list, got {type(data).__name__}")

    return data


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text).strip()
