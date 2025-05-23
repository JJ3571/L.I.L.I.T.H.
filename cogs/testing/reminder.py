import nextcord
from nextcord.ext import commands

from server_configs.config import GUILD_ID


# 

class Reminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name='remind', description="Set a reminder", guild_ids=[GUILD_ID])
    async def remind(self, interaction: nextcord.Interaction, time: int, *, message: str):
        await interaction.response.send_message(f"Reminder set for {time} seconds. Message: {message}", ephemeral=True)
        await nextcord.utils.sleep_until(time)
        await interaction.followup.send(f"Reminder: {message}", ephemeral=True)