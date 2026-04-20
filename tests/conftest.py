"""Shared fixtures: PostgreSQL pool when DATABASE_URL is set."""

from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

from main_bot.db.ddl import init_all_schemas


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg_pool():
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("DATABASE_URL is not set (CI provides Postgres; local: export DATABASE_URL)")

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, command_timeout=60)
    await init_all_schemas(pool)
    try:
        yield pool
    finally:
        await pool.close()
