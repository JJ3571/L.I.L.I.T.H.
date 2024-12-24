import nextcord
from nextcord.ext import commands
import os
import asyncio

from server_configs.config import APPLICATION_ID, DISCORD_BOT_TOKEN, GUILD_ID

# Bot & Intent config
bot = commands.Bot(
    command_prefix='.',
    intents=nextcord.Intents.all(),
    application_id=APPLICATION_ID
)

# Slash command to ensure bot is functional
@bot.slash_command(name="hewwo", description="Hello command", guild_ids=[GUILD_ID])
async def hello(interaction: nextcord.Interaction):
    await interaction.response.send_message(
        f"Hello {interaction.user.mention}!",
        ephemeral=True
    )

# - - - - - - - - Load Cogs - - - - - - - -
def load_extensions():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            bot.load_extension(f'cogs.{filename[:-3]}')
            print(f"Loaded extension: cogs.{filename[:-3]}")

# - - - - - - - - Bot Start - - - - - - - -
async def main():
    load_extensions()

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