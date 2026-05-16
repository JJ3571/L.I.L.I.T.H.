# Bare bones startup script for debugging bot.

import logging
import logging.handlers
import os
from pathlib import Path

import nextcord
from nextcord.ext import commands

from main_bot.paths import runtime_bot_log_path
from main_bot.server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    application_id=APPLICATION_ID,
)

def _rotate_bytes_backup() -> tuple[int, int]:
    raw_m = os.environ.get("BOT_LOG_MAX_BYTES", "10485760").strip()
    try:
        max_bytes = max(4096, int(raw_m))
    except ValueError:
        max_bytes = 10 * 1024 * 1024
    raw_b = os.environ.get("BOT_LOG_BACKUP_COUNT", "5").strip()
    try:
        backup_count = max(1, int(raw_b))
    except ValueError:
        backup_count = 5
    return max_bytes, backup_count


log_path = runtime_bot_log_path()
log_path.parent.mkdir(parents=True, exist_ok=True)
max_bytes, backup_count = _rotate_bytes_backup()
handler = logging.handlers.RotatingFileHandler(
    filename=str(log_path),
    maxBytes=max_bytes,
    backupCount=backup_count,
    encoding="utf-8",
)

logger = logging.getLogger("nextcord")
logger.setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(handler)

COGS_ROOT = Path(__file__).resolve().parents[1] / "cogs"


def load_extensions():
    path = COGS_ROOT / "testing2"
    if not path.is_dir():
        return
    for filename in os.listdir(path):
        if filename.endswith(".py") and filename != "__init__.py":
            bot.load_extension(f"main_bot.cogs.testing2.{filename[:-3]}")


@bot.event
async def on_ready():
    load_extensions()
    print("Bot is ready and running.")


if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
