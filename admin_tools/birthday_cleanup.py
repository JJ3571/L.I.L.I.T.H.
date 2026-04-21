#!/usr/bin/env python3
"""
Birthday cleanup: Postgres schema "birthday". Requires DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg


async def cleanup_birthday_database() -> None:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL is not set.")
        return

    conn = await asyncpg.connect(dsn)
    try:
        print("\n=== Invalid birthday_messages ===")
        rows = await conn.fetch(
            '''
            SELECT user_id, message_id, birthday FROM "birthday".birthday_messages
            WHERE birthday IS NULL OR trim(birthday) = ''
            '''
        )
        if rows:
            for r in rows:
                print(f"  user_id={r['user_id']} message_id={r['message_id']} birthday={r['birthday']!r}")
            response = input("\nDelete these rows? (y/N): ").strip().lower()
            if response == "y":
                await conn.execute(
                    '''
                    DELETE FROM "birthday".birthday_messages
                    WHERE birthday IS NULL OR trim(birthday) = ''
                    '''
                )
                print(f"Deleted {len(rows)} rows.")
        else:
            print("None.")

        print("\n=== Invalid birthdays ===")
        rows2 = await conn.fetch(
            '''
            SELECT user_id, birthday FROM "birthday".birthdays
            WHERE birthday IS NULL OR trim(birthday) = ''
            '''
        )
        if rows2:
            for r in rows2:
                print(f"  user_id={r['user_id']} birthday={r['birthday']!r}")
            response = input("\nDelete these rows? (y/N): ").strip().lower()
            if response == "y":
                await conn.execute(
                    '''
                    DELETE FROM "birthday".birthdays
                    WHERE birthday IS NULL OR trim(birthday) = ''
                    '''
                )
                print(f"Deleted {len(rows2)} rows.")
        else:
            print("None.")
    finally:
        await conn.close()


if __name__ == "__main__":
    print("Birthday cleanup (PostgreSQL)")
    asyncio.run(cleanup_birthday_database())
    print("\nDone.")
