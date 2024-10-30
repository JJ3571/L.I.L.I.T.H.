import discord 
from discord import Intents, Client, Message, app_commands
from discord.ext import commands

import os
import dotenv
import asyncio

# - - - - - - - - Configs - - - - - - - - -
# .env Variable for secret key
DISCORD_BOT_TOKEN = dotenv.dotenv_values(".env")["DISCORD_BOT_TOKEN"]
DISCORD_SERVER_ID = dotenv.dotenv_values(".env")["DISCORD_SERVER_ID"]

# Bot & Intent config
bot = commands.Bot(command_prefix='.', intents=discord.Intents.all())



# - - - Confirm Ready & Test Command - - -
@bot.event
async def on_ready():
    print(f'Bot is ready and running.')
    try:
        synced = await bot.tree.sync()
        print(f"Test /hello command synced.")
    except Exception as e:
        print(f"Error syncing test command:\n{e}")

# Slash command to ensure bot is functional 
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello {interaction.user.mention}!", 
    ephemeral=True)

# - - - - - - - - Load Cogs - - - - - - - -
async def load_extensions():
    bot.load_extension('cogs.movie')
async def main():
    async with bot:
        await load_extensions()
        await bot.start(DISCORD_BOT_TOKEN)
asyncio.run(main())
# - - - - - - - - Bot Start - - - - - - - -
