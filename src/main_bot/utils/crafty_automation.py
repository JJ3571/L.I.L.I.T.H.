import os
import sqlite3
import aiosqlite
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

from main_bot.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

@dataclass
class ServerAutomationConfig:
    """Configuration for server automation settings"""
    server_id: str
    auto_shutdown_enabled: bool = False
    idle_timeout_minutes: int = 10  # Minutes of 0 players before shutdown
    always_online: bool = False     # Never auto-shutdown this server
    last_player_seen: Optional[str] = None  # Timestamp of last player activity

class CraftyAutomationDB:
    """Database manager for Crafty Controller automation settings"""
    
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.fspath(PROJECT_ROOT / "databases" / "crafty_automation.db")
    
    async def init_database(self):
        """Initialize the automation database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS server_automation (
                    server_id TEXT PRIMARY KEY,
                    auto_shutdown_enabled BOOLEAN DEFAULT FALSE,
                    idle_timeout_minutes INTEGER DEFAULT 10,
                    always_online BOOLEAN DEFAULT FALSE,
                    last_player_seen TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS minecraft_whitelist_names (
                    username TEXT PRIMARY KEY NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS server_whitelist_ready (
                    server_id TEXT PRIMARY KEY NOT NULL,
                    whitelist_enabled_confirmed INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
            logger.info("Crafty automation database initialized")
    
    async def get_server_config(self, server_id: str) -> ServerAutomationConfig:
        """Get automation configuration for a server"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM server_automation WHERE server_id = ?", 
                (server_id,)
            ) as cursor:
                row = await cursor.fetchone()
                
                if row:
                    return ServerAutomationConfig(
                        server_id=row[0],
                        auto_shutdown_enabled=bool(row[1]),
                        idle_timeout_minutes=row[2],
                        always_online=bool(row[3]),
                        last_player_seen=row[4]
                    )
                else:
                    # Return default configuration
                    return ServerAutomationConfig(server_id=server_id)
    
    async def update_server_config(self, config: ServerAutomationConfig):
        """Update automation configuration for a server"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO server_automation 
                (server_id, auto_shutdown_enabled, idle_timeout_minutes, always_online, last_player_seen, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                config.server_id,
                config.auto_shutdown_enabled,
                config.idle_timeout_minutes,
                config.always_online,
                config.last_player_seen
            ))
            await db.commit()
    
    async def get_all_monitored_servers(self) -> List[ServerAutomationConfig]:
        """Get all servers with automation enabled"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM server_automation WHERE auto_shutdown_enabled = TRUE AND always_online = FALSE"
            ) as cursor:
                rows = await cursor.fetchall()
                
                return [
                    ServerAutomationConfig(
                        server_id=row[0],
                        auto_shutdown_enabled=bool(row[1]),
                        idle_timeout_minutes=row[2],
                        always_online=bool(row[3]),
                        last_player_seen=row[4]
                    )
                    for row in rows
                ]
    
    async def update_last_player_seen(self, server_id: str, timestamp: str):
        """Update the last time a player was seen on a server"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO server_automation 
                (server_id, last_player_seen, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(server_id) DO UPDATE SET
                last_player_seen = excluded.last_player_seen,
                updated_at = excluded.updated_at
            """, (server_id, timestamp))
            await db.commit()
    
    async def delete_server_config(self, server_id: str):
        """Delete automation configuration for a server"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM server_automation WHERE server_id = ?", (server_id,))
            await db.commit()

    async def add_whitelist_username(self, username: str) -> bool:
        """Add a Minecraft username to the shared list. Returns True if newly inserted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO minecraft_whitelist_names (username) VALUES (?)",
                (username,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def remove_whitelist_username(self, username: str) -> bool:
        """Remove a Minecraft username from the shared list. Returns True if a row was deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM minecraft_whitelist_names WHERE username = ?",
                (username,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_whitelist_usernames(self) -> List[str]:
        """All Minecraft usernames in the shared whitelist list (sorted, case-insensitive)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT username FROM minecraft_whitelist_names ORDER BY username COLLATE NOCASE"
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def get_server_whitelist_ready(self, server_id: str) -> bool:
        """True if this server was marked as having whitelist enabled (via successful apply or manual mark)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT whitelist_enabled_confirmed FROM server_whitelist_ready WHERE server_id = ?",
                (server_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return bool(row[0]) if row else False

    async def set_server_whitelist_ready(self, server_id: str, confirmed: bool) -> None:
        """Persist whether whitelist is known to be enabled on this server."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO server_whitelist_ready (server_id, whitelist_enabled_confirmed, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(server_id) DO UPDATE SET
                    whitelist_enabled_confirmed = excluded.whitelist_enabled_confirmed,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (server_id, 1 if confirmed else 0),
            )
            await db.commit()

    async def clear_server_whitelist_ready(self, server_id: str) -> bool:
        """Forget whitelist-ready state for a server. Returns True if a row existed."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM server_whitelist_ready WHERE server_id = ?",
                (server_id,),
            )
            await db.commit()
            return cursor.rowcount > 0