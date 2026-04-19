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
        "TRUNCATE TABLE tenants, daemon_heartbeat, prompts, operator_secrets RESTART IDENTITY CASCADE"
    )
    # Reset operator_config to defaults (singleton row must always exist).
    await database.execute(
        """
        UPDATE operator_config SET
            llm_provider = 'groq',
            llm_model = 'llama-3.3-70b-versatile',
            llm_temperature = 0.8,
            llm_max_tokens = 2048,
            log_level = 'info',
            share_sweep_cron = '*/10 * * * *',
            startup_grace_seconds = 5,
            updated_at = now()
        WHERE id = 1
        """
    )
    yield database
    await database.close()
