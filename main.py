import nextcord
from nextcord.ext import commands
import dotenv
import os
import asyncio

# Load environment variables
env_vars = dotenv.dotenv_values(".env")
DISCORD_BOT_TOKEN = env_vars["DISCORD_BOT_TOKEN"]
GUILD_ID = int(env_vars["GUILD_ID"])
APPLICATION_ID = int(env_vars["APPLICATION_ID"])

# Bot & Intent config
bot = commands.Bot(
    command_prefix='.',
    intents=nextcord.Intents.all(),
    application_id=APPLICATION_ID
)
# Slash command to ensure bot is functional
@bot.slash_command(name="hello", description="Hello command")
async def hello(interaction: nextcord.Interaction):
    await interaction.response.send_message(
        f"Hello {interaction.user.mention}!",
        ephemeral=True
    )

# - - - - - - - - Load Cogs - - - - - - - -
def load_extensions():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            bot.load_extension(f'cogs.{filename[:-3]}')
            print(f"Loaded extension: cogs.{filename[:-3]}")

# - - - - - - - - Bot Start - - - - - - - -
async def main():
    load_extensions()
    await bot.start(DISCORD_BOT_TOKEN)

@bot.event
async def on_ready():
    print('Bot is ready and running.')
    try:
        # Sync commands to a specific guild during development
        synced = await bot.sync_application_commands(guild_id=GUILD_ID)
        print(f"Synced commands to the guild.")
    except nextcord.HTTPException as e:
        print(f"An error occurred while syncing commands: {e}")

asyncio.run(main())