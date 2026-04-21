import logging
from typing import List, Optional

import asyncpg
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CA = "crafty_automation"


@dataclass
class ServerAutomationConfig:
    """Configuration for server automation settings"""

    server_id: str
    auto_shutdown_enabled: bool = False
    idle_timeout_minutes: int = 10
    always_online: bool = False
    last_player_seen: Optional[str] = None


class CraftyAutomationDB:
    """Database manager for Crafty Controller automation settings (PostgreSQL)."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def init_database(self):
        """Schema is created at bot startup via ddl.init_all_schemas."""
        logger.info("Crafty automation database ready (PostgreSQL).")

    async def get_server_config(self, server_id: str) -> ServerAutomationConfig:
        async with self._pool.acquire() as db:
            row = await db.fetchrow(
                f'SELECT * FROM "{_CA}".server_automation WHERE server_id = $1', server_id
            )
            if row:
                return ServerAutomationConfig(
                    server_id=row["server_id"],
                    auto_shutdown_enabled=row["auto_shutdown_enabled"],
                    idle_timeout_minutes=row["idle_timeout_minutes"],
                    always_online=row["always_online"],
                    last_player_seen=row["last_player_seen"],
                )
            return ServerAutomationConfig(server_id=server_id)

    async def update_server_config(self, config: ServerAutomationConfig):
        async with self._pool.acquire() as db:
            await db.execute(
                f'''
                INSERT INTO "{_CA}".server_automation
                (server_id, auto_shutdown_enabled, idle_timeout_minutes, always_online, last_player_seen, updated_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (server_id) DO UPDATE SET
                    auto_shutdown_enabled = EXCLUDED.auto_shutdown_enabled,
                    idle_timeout_minutes = EXCLUDED.idle_timeout_minutes,
                    always_online = EXCLUDED.always_online,
                    last_player_seen = EXCLUDED.last_player_seen,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                config.server_id,
                config.auto_shutdown_enabled,
                config.idle_timeout_minutes,
                config.always_online,
                config.last_player_seen,
            )

    async def get_all_monitored_servers(self) -> List[ServerAutomationConfig]:
        async with self._pool.acquire() as db:
            rows = await db.fetch(
                f'''
                SELECT * FROM "{_CA}".server_automation
                WHERE auto_shutdown_enabled = TRUE AND always_online = FALSE
                '''
            )
            return [
                ServerAutomationConfig(
                    server_id=row["server_id"],
                    auto_shutdown_enabled=row["auto_shutdown_enabled"],
                    idle_timeout_minutes=row["idle_timeout_minutes"],
                    always_online=row["always_online"],
                    last_player_seen=row["last_player_seen"],
                )
                for row in rows
            ]

    async def update_last_player_seen(self, server_id: str, timestamp: str):
        async with self._pool.acquire() as db:
            await db.execute(
                f'''
                INSERT INTO "{_CA}".server_automation (server_id, last_player_seen, updated_at)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (server_id) DO UPDATE SET
                    last_player_seen = EXCLUDED.last_player_seen,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                server_id,
                timestamp,
            )

    async def delete_server_config(self, server_id: str):
        async with self._pool.acquire() as db:
            await db.execute(
                f'DELETE FROM "{_CA}".server_automation WHERE server_id = $1', server_id
            )

    async def add_whitelist_username(self, username: str) -> bool:
        row = await self._pool.fetchrow(
            f'''
            INSERT INTO "{_CA}".minecraft_whitelist_names (username) VALUES ($1)
            ON CONFLICT (username) DO NOTHING
            RETURNING username
            ''',
            username,
        )
        return row is not None

    async def remove_whitelist_username(self, username: str) -> bool:
        tag = await self._pool.execute(
            f'DELETE FROM "{_CA}".minecraft_whitelist_names WHERE username = $1', username
        )
        return tag != "DELETE 0"

    async def list_whitelist_usernames(self) -> List[str]:
        rows = await self._pool.fetch(
            f'SELECT username FROM "{_CA}".minecraft_whitelist_names ORDER BY LOWER(username)'
        )
        return [r["username"] for r in rows]

    async def get_server_whitelist_ready(self, server_id: str) -> bool:
        row = await self._pool.fetchrow(
            f'''
            SELECT whitelist_enabled_confirmed FROM "{_CA}".server_whitelist_ready WHERE server_id = $1
            ''',
            server_id,
        )
        return bool(row["whitelist_enabled_confirmed"]) if row else False

    async def set_server_whitelist_ready(self, server_id: str, confirmed: bool) -> None:
        await self._pool.execute(
            f'''
            INSERT INTO "{_CA}".server_whitelist_ready (server_id, whitelist_enabled_confirmed, updated_at)
            VALUES ($1, $2, CURRENT_TIMESTAMP)
            ON CONFLICT (server_id) DO UPDATE SET
                whitelist_enabled_confirmed = EXCLUDED.whitelist_enabled_confirmed,
                updated_at = CURRENT_TIMESTAMP
            ''',
            server_id,
            1 if confirmed else 0,
        )

    async def clear_server_whitelist_ready(self, server_id: str) -> bool:
        tag = await self._pool.execute(
            f'DELETE FROM "{_CA}".server_whitelist_ready WHERE server_id = $1', server_id
        )
        return tag != "DELETE 0"
