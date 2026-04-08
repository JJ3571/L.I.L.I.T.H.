# Bare bones startup script for debugging bot.

import logging
import os
from pathlib import Path

import nextcord
from nextcord.ext import commands

from main_bot.paths import PROJECT_ROOT
from main_bot.server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    application_id=APPLICATION_ID,
)

logger = logging.getLogger("nextcord")
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(
    filename=str(PROJECT_ROOT / "nextcord.log"),
    encoding="utf-8",
    mode="w",
)
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
