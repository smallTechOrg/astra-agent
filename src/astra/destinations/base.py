"""Abstract Destination interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astra.config.models import TenantConfig
    from astra.db.connection import Database
    from astra.domain import HealthStatus, PublishEvent, PublishResult


class Destination(ABC):
    """Publishes a single post to a platform endpoint for one tenant.

    Per spec/product/02-architecture.md#destination. All secrets are
    injected at call time (P5 — not stored on module state).
    """

    @abstractmethod
    async def publish(
        self,
        tenant: TenantConfig,
        event: PublishEvent,
        copy: str,
        db: Database,
        *,
        access_token: str,
    ) -> PublishResult:
        """Post *copy* with a reference to *event*. Returns typed result."""
        ...

    @abstractmethod
    async def health_check(
        self,
        tenant: TenantConfig,
        *,
        access_token: str,
    ) -> HealthStatus:
        """Probe whether this destination is currently usable."""
        ...
