import nextcord
from nextcord.ext import commands
import os

from server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID

# - - - - - - - - Logging - - - - - - - -
import logging
# logging.basicConfig(level=logging.INFO) # Terminal output log
logger = logging.getLogger('nextcord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='nextcord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Bot & Intent config
intents=nextcord.Intents.default()
intents.message_content=True
intents.members=True
intents.guilds=True
intents.reactions=True
# intents.presences=True 
intents.emojis_and_stickers=True
# intents.voice_states=True
intents.guild_messages=True
intents.guild_reactions=True

bot = commands.Bot(
    command_prefix='.',
    intents=intents,
    application_id=APPLICATION_ID
)

# - - - - - - - - Load Cogs (Generic from Cogs folder)- - - - - - - -
# def load_extensions():
#     for filename in os.listdir('./cogs'):
#         if filename.endswith('.py') and filename != '__init__.py':
#             bot.load_extension(f'cogs.{filename[:-3]}')
#             print(f"Loaded extension: cogs.{filename[:-3]}")


# - - - - - - - - Load Cogs (based on env folder name) - - - - - - - -
async def load_extensions(directory: str):
    path = f'./cogs/{directory}'
    for filename in os.listdir(path):
        if filename.endswith('.py') and filename != '__init__.py':
            bot.load_extension(f'cogs.{directory}.{filename[:-3]}')
            print(f"Loaded extension: cogs.{directory}.{filename[:-3]}")


# - - - - - - - - Bot Start - - - - - - - -
@bot.event
async def on_ready():
    try:
        await load_extensions('production')
        await bot.sync_application_commands(guild_id=GUILD_ID)
        print('Bot is ready and running.')
    except nextcord.HTTPException as e:
        print(f"An error occurred while syncing commands: {e}")

if __name__ == "__main__":
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        bot.close()
        print("Bot has been stopped.")
    except Exception as e:
                print(f"An error occurred: {e}")