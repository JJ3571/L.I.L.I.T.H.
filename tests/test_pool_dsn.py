"""Tests for PostgreSQL DSN normalization (Neon TLS vs bundled Docker)."""

from __future__ import annotations

import pytest

from main_bot.db.pool import _normalize_postgres_dsn


@pytest.mark.parametrize(
    ("url", "expected_fragment"),
    [
        (
            "postgresql://u:p@localhost:5432/db",
            "postgresql://u:p@localhost:5432/db",
        ),
        (
            "postgresql://u:p@127.0.0.1:5432/db",
            "postgresql://u:p@127.0.0.1:5432/db",
        ),
        (
            "postgresql://u:p@postgres:5432/discord_bot",
            "postgresql://u:p@postgres:5432/discord_bot",
        ),
        (
            "postgresql://u:p@neon.tech.aws/db",
            "sslmode=require",
        ),
        (
            "postgresql://u:p@neon.tech.aws/db?sslmode=disable",
            "sslmode=disable",
        ),
        (
            "postgres://u:p@example.com/db",
            "sslmode=require",
        ),
        (
            "postgresql+asyncpg://u:p@example.com/db",
            "sslmode=require",
        ),
    ],
)
def test_normalize_postgres_dsn(url: str, expected_fragment: str) -> None:
    out = _normalize_postgres_dsn(url)
    if expected_fragment.startswith("postgresql://"):
        assert out == expected_fragment
    else:
        assert expected_fragment in out


def test_normalize_aliases_remote_host_to_postgresql_scheme() -> None:
    out = _normalize_postgres_dsn("postgres://u:p@remote.host/db")
    assert out.startswith("postgresql://")
    assert "sslmode=require" in out
