"""Daily full-database pg_dump backup posted to Discord."""

from __future__ import annotations

import asyncio
import gzip
import os
import tempfile
from datetime import date, datetime

import nextcord
from nextcord.ext import commands, tasks

import pytz

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import backup_channel_id


class DatabaseBackupCog(commands.Cog, CogLogMixin):
    """Runs pg_dump on the configured Postgres URL and uploads gzip to the backup channel once per day."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_backup_date: date | None = None
        self.daily_backup.start()

    def cog_unload(self) -> None:
        self.daily_backup.cancel()

    @tasks.loop(minutes=1)
    async def daily_backup(self):
        await self.bot.wait_until_ready()
        pacific = pytz.timezone("US/Pacific")
        now = datetime.now(pacific)
        if now.hour != 3 or now.minute != 0:
            return
        today = now.date()
        if self._last_backup_date == today:
            return
        self._last_backup_date = today
        await self._run_backup(now)

    @daily_backup.before_loop
    async def before_daily_backup(self):
        await self.bot.wait_until_ready()

    async def _run_backup(self, now: datetime) -> None:
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            self.cog_print("DATABASE_BACKUP: DATABASE_URL not set; skipping.")
            return
        channel = self.bot.get_channel(backup_channel_id)
        if not channel:
            self.cog_print(f"DATABASE_BACKUP: channel {backup_channel_id} not found.")
            return

        stamp = now.strftime("%Y%m%d_%H%M%S")
        fd, raw_path = tempfile.mkstemp(suffix=".sql")
        os.close(fd)
        gz_path = raw_path + ".gz"
        try:
            with open(raw_path, "wb") as out_f:
                proc = await asyncio.create_subprocess_exec(
                    "pg_dump",
                    dsn,
                    "--no-owner",
                    "--no-acl",
                    stdout=out_f,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    err = (stderr or b"").decode("utf-8", errors="replace")[:500]
                    self.cog_print(f"DATABASE_BACKUP: pg_dump failed: {err}")
                    return

            with open(raw_path, "rb") as fin, gzip.open(gz_path, "wb") as fout:
                fout.writelines(fin)
            os.remove(raw_path)
            raw_path = ""

            size = os.path.getsize(gz_path)
            max_bytes = 8 * 1024 * 1024
            if size > max_bytes:
                self.cog_print(
                    f"DATABASE_BACKUP: gzip size {size} exceeds ~8MB; upload may fail."
                )

            fname = f"bot_db_backup_{stamp}.sql.gz"
            with open(gz_path, "rb") as fp:
                await channel.send(
                    content=f"Scheduled database backup (`{fname}`).",
                    file=nextcord.File(fp, filename=fname),
                )
            self.cog_print("DATABASE_BACKUP: uploaded successfully.")
        except FileNotFoundError:
            self.cog_print(
                "DATABASE_BACKUP: pg_dump not found on PATH. Install PostgreSQL client tools on the host."
            )
        except Exception as e:
            self.cog_print(f"DATABASE_BACKUP: error: {e}")
        finally:
            for p in (raw_path, gz_path):
                if p and os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DatabaseBackupCog(bot))
    boot_print("DatabaseBackupCog loaded.")
