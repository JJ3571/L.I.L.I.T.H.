"""asyncpg connection pool lifecycle."""

from __future__ import annotations

import os
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in Doppler or the environment "
            "(e.g. Neon connection string)."
        )
    return url


async def create_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    dsn = get_database_url()
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=10,
        command_timeout=60,
    )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool is not initialized")
    return _pool
