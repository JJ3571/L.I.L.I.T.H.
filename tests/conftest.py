"""Shared fixtures: PostgreSQL pool when DATABASE_URL is set."""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

from main_bot.db.ddl import init_all_schemas


@pytest.fixture(scope="module")
def pg_pool():
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("DATABASE_URL is not set (CI provides Postgres; local: export DATABASE_URL)")

    async def _init() -> asyncpg.Pool:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, command_timeout=60)
        await init_all_schemas(pool)
        return pool

    pool = asyncio.run(_init())
    yield pool

    async def _close() -> None:
        await pool.close()

    asyncio.run(_close())
