#!/usr/bin/env python3
"""
Database verification: PostgreSQL schemas (Neon/self-hosted).
Requires DATABASE_URL. Lists tables per schema and runs sanity checks.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg

from main_bot.db.ddl import init_all_schemas
from main_bot.server_configs.database_config import SCHEMA_KEYS


class DatabaseVerifier:
    def __init__(self) -> None:
        self.issues_found: list[dict] = []
        self.schemas_checked = 0
        self.tables_verified = 0

    def log_issue(self, severity: str, schema: str, message: str) -> None:
        self.issues_found.append(
            {
                "severity": severity,
                "database": schema,
                "message": message,
                "timestamp": datetime.now(),
            }
        )
        print(f"[{severity.upper()}] {schema}: {message}")

    async def verify(self) -> bool:
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            self.log_issue("ERROR", "postgres", "DATABASE_URL is not set")
            return False

        print("PostgreSQL verification (schemas)")
        print("=" * 50)

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, command_timeout=60)
        try:
            await init_all_schemas(pool)

            async with pool.acquire() as conn:
                for key in SCHEMA_KEYS:
                    self.schemas_checked += 1
                    print(f"Schema: {key}")
                    rows = await conn.fetch(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = $1 AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """,
                        key,
                    )
                    names = [r["table_name"] for r in rows]
                    print(f"  tables ({len(names)}): {', '.join(names) if names else '—'}")
                    for t in names:
                        n = await conn.fetchval(
                            f'SELECT COUNT(*) FROM "{key}"."{t}"'
                        )
                        self.tables_verified += 1
                        print(f"    {t}: {n} rows")

                    await self._schema_checks(conn, key)
                    print()

            errors = [i for i in self.issues_found if i["severity"] == "ERROR"]
            print("Summary")
            print("=" * 30)
            print(f"Schemas: {self.schemas_checked}, table counts read: {self.tables_verified}")
            print(f"Issues: {len(self.issues_found)}")
            return len(errors) == 0
        finally:
            await pool.close()

    async def _schema_checks(self, conn: asyncpg.Connection, key: str) -> None:
        if key == "economy":
            try:
                neg = await conn.fetchval(f'SELECT COUNT(*) FROM "{key}".users WHERE balance < 0')
                if neg and neg > 0:
                    self.log_issue("WARNING", key, f"{neg} users have negative balances")
            except Exception as e:
                self.log_issue("ERROR", key, str(e))
        if key == "birthday":
            try:
                bad = await conn.fetchval(
                    f'''
                    SELECT COUNT(*) FROM "{key}".birthday_messages
                    WHERE birthday IS NULL OR trim(birthday::text) = ''
                    '''
                )
                if bad and bad > 0:
                    self.log_issue("WARNING", key, f"{bad} birthday_messages rows with empty birthday")
            except Exception as e:
                self.log_issue("ERROR", key, str(e))
        if key == "powerups":
            try:
                import time

                now = int(time.time())
                exp = await conn.fetchval(
                    f'SELECT COUNT(*) FROM "{key}".active_powerups WHERE end_time < $1',
                    now,
                )
                if exp and exp > 0:
                    self.log_issue("INFO", key, f"{exp} expired active_powerups rows (cleanup task may remove)")
            except Exception as e:
                self.log_issue("ERROR", key, str(e))


async def main() -> int:
    ok = await DatabaseVerifier().verify()
    print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(1)
