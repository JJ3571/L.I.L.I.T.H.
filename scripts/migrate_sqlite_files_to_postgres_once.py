#!/usr/bin/env python3
"""
One-time migration: legacy SQLite files under databases/*.db -> one PostgreSQL database,
one schema per former file (same names as DATABASE_PATHS keys).

Prerequisites:
  - DATABASE_URL (postgresql://..., sslmode=require for Neon)
  - Python deps from this repo (uv sync)
  - Source SQLite files present (gitignored) where DATABASE_PATHS points

Usage:
  uv run python scripts/migrate_sqlite_files_to_postgres_once.py --dry-run
  uv run python scripts/migrate_sqlite_files_to_postgres_once.py --only economy

Safety: never paste production URLs into public chats. Prefer a staging Neon branch first.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from main_bot.db.ddl import init_all_schemas
from main_bot.server_configs.database_config import DATABASE_PATHS


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r[0] for r in cur.fetchall()]


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return list(conn.execute(f"PRAGMA table_info({table})").fetchall())


async def _copy_table(
    *,
    pg: asyncpg.Connection,
    schema: str,
    sconn: sqlite3.Connection,
    table: str,
    dry_run: bool,
) -> tuple[int, bool]:
    cols = _sqlite_columns(sconn, table)
    if not cols:
        return 0, True
    col_names = [c[1] for c in cols]
    quoted = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(f"${i}" for i in range(1, len(col_names) + 1))
    sql = f'INSERT INTO "{schema}"."{table}" ({quoted}) VALUES ({placeholders})'
    rows = sconn.execute(f"SELECT * FROM {table}").fetchall()
    if dry_run:
        return len(rows), True

    n = 0
    for row in rows:
        vals: list[Any] = []
        for v in row:
            if isinstance(v, bytes):
                vals.append(v.decode("utf-8", errors="replace"))
            else:
                vals.append(v)
        try:
            await pg.execute(sql, *vals)
            n += 1
        except asyncpg.UniqueViolationError:
            continue
        except asyncpg.ForeignKeyViolationError:
            return n, False
    return n, True


async def migrate_schema(
    pool: asyncpg.Pool,
    key: str,
    sqlite_path: str,
    *,
    dry_run: bool,
    rounds: int,
) -> None:
    if not os.path.isfile(sqlite_path):
        print(f"  skip (missing file): {sqlite_path}")
        return
    print(f"  {key}: {sqlite_path}")
    sconn = sqlite3.connect(sqlite_path)
    try:
        sconn.execute("PRAGMA foreign_keys = OFF")
        tables = _sqlite_tables(sconn)
        async with pool.acquire() as pg:
            left: set[str] = set(tables)
            total = 0
            for _ in range(rounds):
                if not left:
                    break
                progressed = False
                for t in sorted(left):
                    try:
                        n, ok = await _copy_table(
                            pg=pg, schema=key, sconn=sconn, table=t, dry_run=dry_run
                        )
                        total += n
                        if ok:
                            left.discard(t)
                        progressed = True
                    except Exception as e:
                        print(f"    defer {t}: {e}")
                if not progressed:
                    break
            if left:
                print(f"    WARNING: could not import tables: {', '.join(sorted(left))}")
            else:
                print(f"    OK ({total} inserts attempted)" + (" [dry-run]" if dry_run else ""))
    finally:
        sconn.close()


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Connect and list work without writing rows")
    p.add_argument("--only", help="Only migrate this DATABASE_PATHS key (e.g. economy)")
    p.add_argument("--rounds", type=int, default=12, help="Retry passes for FK ordering")
    args = p.parse_args()

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, command_timeout=120)
    try:
        if not args.dry_run:
            await init_all_schemas(pool)
        keys: Iterable[str]
        if args.only:
            keys = [args.only]
            if args.only not in DATABASE_PATHS:
                print(f"Unknown key: {args.only}", file=sys.stderr)
                return 1
        else:
            keys = DATABASE_PATHS.keys()

        for key in keys:
            await migrate_schema(pool, key, DATABASE_PATHS[key], dry_run=args.dry_run, rounds=args.rounds)

        # crafty_automation file
        from main_bot.server_configs.database_config import CRAFTY_AUTOMATION_SQLITE_PATH

        if os.path.isfile(CRAFTY_AUTOMATION_SQLITE_PATH) and (args.only is None or args.only == "crafty_automation"):
            await migrate_schema(
                pool,
                "crafty_automation",
                CRAFTY_AUTOMATION_SQLITE_PATH,
                dry_run=args.dry_run,
                rounds=args.rounds,
            )

    finally:
        await pool.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
