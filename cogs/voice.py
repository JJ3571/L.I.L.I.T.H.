import nextcord
from nextcord import SlashOption
from nextcord.ext import commands
import datetime, re
import asyncio

from server_configs.config import GUILD_ID
from server_configs.cogs_config import allowed_user_ids, voice_channel_ids, create_fireteam_channel_id, seen_category_id, hidden_category_id, league_channel_id

class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reserved_channels = {}  # channel_id: timestamp when reservation ends
        print("Initializing VoiceCog.")

    def cog_unload(self):
        print("VoiceCog has been unloaded.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            print(f"Categories not found in guild '{guild.name}'.")
            return

        # User joins the create_fireteam channel
        if after.channel and after.channel.id == create_fireteam_channel_id:
            print(f"{member.name} has joined the create_fireteam channel.")
            # Move a voice channel from hidden_category to seen_category
            moved_channel = None
            for channel_id in voice_channel_ids:
                channel = guild.get_channel(channel_id)
                if channel and channel.category and channel.category.id == hidden_category_id:
                    overwrites = channel.overwrites
                    # Allow @everyone to view the channel
                    overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
                    await channel.edit(category=seen_category, overwrites=overwrites)
                    moved_channel = channel
                    print(f"Moved '{channel.name}' to seen category and updated permissions.")
                    break  # Move only one channel

            if moved_channel:
                # Move the member to the newly moved channel
                await member.move_to(moved_channel)
                print(f"Moved {member.name} to '{moved_channel.name}'.")

        # Handle channels becoming empty or occupied
        if before.channel and before.channel.id in voice_channel_ids:
            if len(before.channel.members) == 0 and before.channel.id not in self.reserved_channels:
                await self.hide_channel(before.channel)
            else:
                self.reserved_channels.pop(before.channel.id, None)

        if after.channel and after.channel.id in voice_channel_ids:
            self.reserved_channels.pop(after.channel.id, None)

        # Handle league channel
        if before.channel and before.channel.id == league_channel_id:
            if len(before.channel.members) == 0:
                await self.hide_channel(before.channel)

    async def hide_channel(self, channel):
        guild = channel.guild
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            print(f"Hidden category not found in guild '{guild.name}'.")
            return

        overwrites = channel.overwrites
        # Deny @everyone the permission to view the channel
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
        await channel.edit(category=hidden_category, overwrites=overwrites)
        print(f"Moved '{channel.name}' to hidden category and updated permissions.")

    @nextcord.slash_command(name="tidy_up", description="Manually tidy up voice channels.")
    async def tidy_up(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id not in allowed_user_ids:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.name} attempted to use tidy_up without permission.")
            return

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            await interaction.followup.send("Categories not found.", ephemeral=True)
            print("Categories not found during tidy_up command.")
            return

        for channel_id in voice_channel_ids:
            channel = guild.get_channel(channel_id)
            if channel and channel.category and channel.category.id == seen_category_id:
                await self.hide_channel(channel)

        await interaction.followup.send("Voice channels have been tidied up.", ephemeral=True)
        print(f"{interaction.user.name} ran tidy_up command.")

    @nextcord.slash_command(name="reserve_channel", description="Reserve a voice channel for a set amount of time.")
    async def reserve_channel(
        self,
        interaction: nextcord.Interaction,
        duration: int,
        unit: str = SlashOption(
            name="unit",
            description="Select the time unit",
            choices={"minutes": "minutes", "hours": "hours"}
        )
    ):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id not in allowed_user_ids:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.name} attempted to use reserve_channel without permission.")
            return

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        channel_id = interaction.channel_id
        channel = guild.get_channel(channel_id)
        if not channel or channel.id not in voice_channel_ids:
            await interaction.followup.send("Invalid channel ID.", ephemeral=True)
            return

        if unit == "minutes":
            reservation_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration)
            delay = duration * 60
        elif unit == "hours":
            reservation_time = datetime.datetime.utcnow() + datetime.timedelta(hours=duration)
            delay = duration * 3600
        else:
            await interaction.followup.send("Invalid time unit. Use 'minutes' or 'hours'.", ephemeral=True)
            return

        self.reserved_channels[channel_id] = reservation_time
        await interaction.followup.send(f"Reserved channel {channel.name} for {duration} {unit}.", ephemeral=True)
        print(f"{interaction.user.name} reserved channel {channel.name} for {duration} {unit}.")

        # Schedule the task to move the channel after the specified duration
        asyncio.create_task(self.move_channel_to_hidden(guild, channel, delay))

    async def move_channel_to_hidden(self, guild, channel, delay):
        await asyncio.sleep(delay)
        hidden_category = guild.get_channel(hidden_category_id)
        if hidden_category:
            await channel.edit(category=hidden_category)
            print(f"Moved channel {channel.name} to hidden category after reservation time.")

    @nextcord.slash_command(name="create_temp_channel", description="Create a temporary voice channel with a custom name.")
    async def create_temp_channel(self, interaction: nextcord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id not in allowed_user_ids:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.name} attempted to use create_temp_channel without permission.")
            return

        if not re.match(r'^[\w-]+$', name):
            await interaction.followup.send("Invalid channel name. Use only letters, numbers, hyphens, and underscores.", ephemeral=True)
            return

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            await interaction.followup.send("Seen category not found.", ephemeral=True)
            return

        temp_channel = await guild.create_voice_channel(name, category=seen_category)
        await interaction.followup.send(f"Created temporary voice channel: {name}", ephemeral=True)
        print(f"{interaction.user.name} created temporary voice channel: {name}")

        def check_empty_channel(channel):
            return len(channel.members) == 0

        while True:
            await asyncio.sleep(10)
            if check_empty_channel(temp_channel):
                await temp_channel.delete()
                print(f"Deleted temporary voice channel: {name}")
                break

    @nextcord.slash_command(name="league", description="Pull the league channel out of the hidden category.")
    async def league(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id not in allowed_user_ids:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.name} attempted to use league without permission.")
            return

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        league_channel = guild.get_channel(league_channel_id)
        if not league_channel:
            await interaction.followup.send("League channel not found.", ephemeral=True)
            return

        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            await interaction.followup.send("Seen category not found.", ephemeral=True)
            return

        overwrites = league_channel.overwrites
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
        await league_channel.edit(category=seen_category, overwrites=overwrites)
        await interaction.followup.send("League channel has been moved to the seen category.", ephemeral=True)
        print(f"League channel '{league_channel.name}' moved to seen category.")

async def setup(bot):
    bot.add_cog(VoiceCog(bot))
    print("VoiceCog has been added to the bot.")