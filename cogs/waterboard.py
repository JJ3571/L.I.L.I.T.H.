import nextcord
from nextcord import SlashOption
from nextcord.ext import commands
import asyncio

from server_configs.config import GUILD_ID
from server_configs.cogs_config import admin_user_ids, seen_category_id, hidden_category_id

class WaterCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_channels = []
        self.active_waterboards = set()
        print("Initializing WaterCog.")

    @nextcord.slash_command(name="waterboard", description="Waterboard a user by moving them through multiple channels.", guild_ids=[GUILD_ID])
    async def waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member = SlashOption(description="The user to waterboard")):
        if user.id in self.active_waterboards:
            await interaction.response.send_message(f"{user.mention} is already being waterboarded.", ephemeral=True)
            return

        self.active_waterboards.add(user.id)
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            await interaction.followup.send("Seen category not found.", ephemeral=True)
            self.active_waterboards.remove(user.id)
            return

        # List of water/ocean names
        water_names = [
            "💧🌊💧🌊", "🌊🐟🌊💧", "💧💧💧🏞️", "💧🐟💧🐟", "💧💧🐟💧",
            "🐟💧💧🌊", "💧💧💧💧", "💧🏝️💧💧", "🌊💧💧💧", "💧💧🐟🌊"
        ]

        # Create temporary channels if they do not already exist
        if not self.temp_channels:
            for name in water_names:
                channel = await guild.create_voice_channel(name, category=seen_category)
                self.temp_channels.append(channel)

        # Remember the user's original channel
        original_channel = user.voice.channel if user.voice else None

        # Move the user through the temporary channels
        for channel in self.temp_channels:
            await user.move_to(channel)
            await asyncio.sleep(1)  # Adjust the sleep time as needed

        # Move the user back to their original channel
        if original_channel:
            await user.move_to(original_channel)

        self.active_waterboards.remove(user.id)

        # Delete the temporary channels if no active waterboards
        if not self.active_waterboards:
            for channel in self.temp_channels:
                await channel.delete()
            self.temp_channels.clear()

        await interaction.followup.send(f"Waterboarded {user.mention} through multiple channels.", ephemeral=True)

def setup(bot):
    bot.add_cog(WaterCog(bot))