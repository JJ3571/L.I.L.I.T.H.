"""asyncpg connection pool lifecycle."""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import asyncpg

_pool: Optional[asyncpg.Pool] = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in Doppler or the environment "
            "(e.g. Neon connection string)."
        )
    return _normalize_postgres_dsn(url)


def _normalize_postgres_dsn(url: str) -> str:
    """asyncpg + Neon: missing TLS params often yields RST during ``start_tls``."""
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if u.startswith(prefix):
            u = "postgresql://" + u[len(prefix) :]
            break
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or not host:
        return u
    pairs = list(parse_qsl(parsed.query, keep_blank_values=True))
    if not any(k.lower() == "sslmode" for k, _ in pairs):
        pairs.append(("sslmode", "require"))
    new_query = urlencode(pairs)
    return urlunparse(parsed._replace(query=new_query))


async def create_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    dsn = get_database_url()
    try:
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
    except ConnectionResetError as e:
        raise RuntimeError(
            "PostgreSQL disconnected during the TLS handshake (connection reset). "
            "For Neon or other cloud Postgres, ensure DATABASE_URL includes "
            "`sslmode=require` (the pool layer adds this for non-local hosts if missing). "
            "Also verify the URL, IP allowlists, VPN, and that the project is not paused."
        ) from e
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
