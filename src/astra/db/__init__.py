"""PostgreSQL persistence layer.

Per spec/product/07-data-model.md: PostgreSQL via asyncpg, one database
for all tenants, every non-tenants table scoped by `tenant_id` with
P1-enforced queries (spec/engineering/tenant-isolation.md).
"""

from __future__ import annotations

from astra.db.connection import Database
from astra.db.migrations import CURRENT_SCHEMA_VERSION, migrate

__all__ = ["CURRENT_SCHEMA_VERSION", "Database", "migrate"]
