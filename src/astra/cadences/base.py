"""Abstract Cadence interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra.config.models import CadenceConfig, TenantConfig
    from astra.db.connection import Database
    from astra.domain import TweetResult
    from astra.llm.base import LLMClient
    from astra.prompts.resolver import PromptResolver


class Cadence(ABC):
    """Independently-scheduled tweet-posting job.

    Per spec/product/02-architecture.md#cadence: one tick = one tweet or skip.
    No retries within a tick; next cron tick is the retry.
    """

    @abstractmethod
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
        """Execute one cadence tick. Returns None only on hard skip (disabled)."""
        ...
