"""Discord bot: intents, bot instance, cog loading, and run()."""

# When True, selected cogs print verbose ``[DEBUG]`` lines to stdout (e.g. birthday and reminder loops).
FULL_DEBUG_IN_TERMINAL = False

# When True, ``on_ready`` also loads ``main_bot.cogs.development`` after production.
# Production cogs always load. Set ``LOAD_DEVELOPMENT_COGS`` in the environment to
# ``1`` / ``true`` / ``yes`` / ``on`` or ``0`` / ``false`` / ``no`` / ``off`` to override
# this default without editing code (e.g. per Doppler config).
DEVELOPMENT_COG_EXTENSIONS_ENABLED = False

import logging
import os
import sys
import traceback
from pathlib import Path

import nextcord

# Wavelink imports ``discord``; alias Nextcord so Lavalink voice protocol matches our Bot/VoiceChannel types.
sys.modules["discord"] = nextcord

from nextcord.ext import commands

from main_bot.boot_log import boot_print
from main_bot.nextcord_voice_gateway_patch import apply_nextcord_voice_gateway_v8_patch
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
        try:
            import wavelink

            await wavelink.Pool.close()
        except Exception:
            pass
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


def _should_load_development_cog_extensions() -> bool:
    raw = os.environ.get("LOAD_DEVELOPMENT_COGS", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return DEVELOPMENT_COG_EXTENSIONS_ENABLED


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

apply_nextcord_voice_gateway_v8_patch()
boot_print(
    "Voice WebSocket gateway patched to v=8 (PyPI nextcord uses legacy v=4 URL). "
    "If logs show close 4017 (DAVE/E2EE required), nextcord cannot negotiate that yet — "
    "see main_bot.nextcord_voice_gateway_patch module docstring.",
)

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
        if _should_load_development_cog_extensions():
            boot_print("Loading development cog extensions (toggle or LOAD_DEVELOPMENT_COGS is on).")
            await load_extensions("development")
        await bot.sync_application_commands(guild_id=GUILD_ID)
        print("[STARTUP_SUCCESS] Bot is ready and running.")
    except nextcord.HTTPException as e:
        print(f"An error occurred while syncing commands: {e}")


def run() -> None:
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        # ``Client.run`` already closes the bot in ``finally`` (``await self.close()`` → ``wavelink.Pool.close()``).
        print("[SHUTDOWN] Bot has been stopped.")
    except Exception as e:
        print(f"An error occurred: {e}")
        traceback.print_exception(type(e), e, e.__traceback__)
