import nextcord
from nextcord.ext import commands
import os
import asyncio

from server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID

# Logging setup
import logging
# logging.basicConfig(level=logging.INFO) # Terminal output log
logger = logging.getLogger('nextcord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='nextcord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Bot & Intent config
bot = commands.Bot(
    command_prefix='.',
    intents=nextcord.Intents.all(),
    application_id=APPLICATION_ID
)


# - - - - - - - - Load Cogs (Generic from Cogs folder)- - - - - - - -
# def load_extensions():
#     for filename in os.listdir('./cogs'):
#         if filename.endswith('.py') and filename != '__init__.py':
#             bot.load_extension(f'cogs.{filename[:-3]}')
#             print(f"Loaded extension: cogs.{filename[:-3]}")

# - - - - - - - - Load Cogs (based on env folder name) - - - - - - - -
def load_extensions(directory: str):
    path = f'./cogs/{directory}'
    for filename in os.listdir(path):
        if filename.endswith('.py') and filename != '__init__.py':
            bot.load_extension(f'cogs.{directory}.{filename[:-3]}')
            print(f"Loaded extension: cogs.{directory}.{filename[:-3]}")

# - - - - - - - - Bot Start - - - - - - - -
async def main():
    load_extensions('production')

    async def close_bot():
        await bot.close()

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        await close_bot()

@bot.event
async def on_ready():
    print('Bot is ready and running.')
    try:
        synced = await bot.sync_application_commands(guild_id=GUILD_ID)
        print(f"Synced commands to the guild.")
    except nextcord.HTTPException as e:
        print(f"An error occurred while syncing commands: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot has been stopped.")