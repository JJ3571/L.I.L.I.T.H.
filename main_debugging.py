# Bare bones startup script for debugging bot.

import asyncio
import os
import nextcord
from nextcord.ext import commands

from server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='.',
    intents=intents,
    application_id=APPLICATION_ID
)

import logging
# logging.basicConfig(level=logging.INFO) # Terminal output log
logger = logging.getLogger('nextcord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='nextcord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


async def load_extensions():
    for filename in os.listdir('./testing2'):
        if filename.endswith('.py') and filename != '__init__.py':
            await bot.load_extension(f'cogs.testing2.{filename[:-3]}')

async def main():
    await load_extensions()
    await bot.start(DISCORD_BOT_TOKEN)
    print("Bot started.")

bot.run(DISCORD_BOT_TOKEN)

@bot.event
async def on_ready():
    print('Bot is ready and running.')