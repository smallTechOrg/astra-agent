"""Shared test fixtures for PostgreSQL-based tests.

Set DATABASE_URL env var to override the default test DSN.
Default: postgresql://astra:astra@localhost:5432/astra_test
"""

from __future__ import annotations

import os

import pytest

from astra.db import Database, migrate

TEST_DSN = os.environ.get("DATABASE_URL", "postgresql://astra:astra@localhost:5432/astra_test")


@pytest.fixture
async def db() -> Database:
    database = Database(TEST_DSN)
    await database.connect()
    await migrate(database)
    # Reset data between tests; CASCADE clears all child tables.
    await database.execute(
        "TRUNCATE TABLE tenants, daemon_heartbeat, prompts RESTART IDENTITY CASCADE"
    )
    yield database
    await database.close()
