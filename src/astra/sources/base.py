"""Abstract Source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra.config.models import TenantConfig
    from astra.db.connection import Database
    from astra.domain import PublishEvent


class Source(ABC):
    """Produces publish events for a tenant.

    per spec/product/02-architecture.md#source:
    - poll() is idempotent: calling twice never returns the same event twice
      after the first has been persisted.
    """

    @abstractmethod
    async def poll(
        self,
        tenant: TenantConfig,
        db: Database,
        *,
        app_password: str,
    ) -> list[PublishEvent]:
        """Return newly-detected publish events.

        *app_password* is the resolved secret (P5 — injected, not stored).
        """
        ...
