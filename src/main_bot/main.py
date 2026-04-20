"""Discord bot: intents, bot instance, cog loading, and run()."""

# When True, selected cogs print verbose ``[DEBUG]`` lines to stdout (e.g. birthday and reminder loops).
FULL_DEBUG_IN_TERMINAL = False

### -------------------------------------------
# nextcord.health_check imports pkg_resources; 
# setuptools emits UserWarning until nextcord migrates.
# dependency version <81 is already pinned in pyproject.toml 

import warnings
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API",
    category=UserWarning,
)
### -------------------------------------------

import logging
import os
from pathlib import Path

import nextcord
from nextcord.ext import commands

from main_bot.boot_log import boot_print
from main_bot.db.ddl import init_all_schemas
from main_bot.db.pool import close_pool, create_pool
from main_bot.error_alerts import ensure_asyncio_exception_handler, install_error_alerts
from main_bot.paths import PROJECT_ROOT
from main_bot.server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID


class MainBot(commands.Bot):
    # PostgreSQL before gateway: nextcord does not run discord.py's ``setup_hook`` on this path.
    async def login(self, token: str) -> None:
        pool = await create_pool()
        self.pg_pool = pool
        await init_all_schemas(pool)
        boot_print("PostgreSQL pool ready and schemas initialized.")
        await super().login(token)

    async def close(self) -> None:
        await close_pool()
        await super().close()


def _setup_logging() -> None:
    logger = logging.getLogger("nextcord")
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(
        filename=str(PROJECT_ROOT / "nextcord.log"),
        encoding="utf-8",
        mode="w",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(handler)


COGS_ROOT = Path(__file__).resolve().parent / "cogs"


async def load_extensions(directory: str) -> None:
    path = COGS_ROOT / directory
    for filename in os.listdir(path):
        if filename.endswith(".py") and filename != "__init__.py":
            ext = f"main_bot.cogs.{directory}.{filename[:-3]}"
            if ext in bot.extensions:
                continue
            bot.load_extension(ext)
            boot_print(f"Loaded extension: {ext}")


_setup_logging()

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True
intents.emojis_and_stickers = True
intents.voice_states = True
intents.guild_messages = True
intents.guild_reactions = True

bot = MainBot(
    command_prefix=".",
    intents=intents,
    application_id=APPLICATION_ID,
)
bot.full_debug_in_terminal = FULL_DEBUG_IN_TERMINAL

install_error_alerts(bot)


@bot.event
async def on_ready():
    await ensure_asyncio_exception_handler(bot)
    try:
        await load_extensions("production") 
        await bot.sync_application_commands(guild_id=GUILD_ID)
        print("[STARTUP_SUCCESS] Bot is ready and running.")
    except nextcord.HTTPException as e:
        print(f"An error occurred while syncing commands: {e}")


def run() -> None:
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        bot.close()
        print(f"[SHUTDOWN] Bot has been stopped.")
    except Exception as e:
        print(f"An error occurred: {e}")
