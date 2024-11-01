import nextcord
from nextcord.ext import commands, tasks
import datetime

INACTIVITY_THRESHOLD = 10  # In seconds (1 minute)
CHECK_INTERVAL = 10  # In seconds

voice_channels = [
    1301726027982180433,  # Fireteam 1
    1301726164208844864,  # Fireteam 2
    1301726212934209576,  # Fireteam 3
]

seen_category_id = 1299278913616482305
hidden_category_id = 1300918817278529557
create_fireteam_channel_id = 421980223391924235
allowed_user_ids = [321888250136363009, 321888250136363009]  # Replace with actual user IDs

class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.empty_voice_channels = {}  # channel_id: timestamp when it became empty
        print("Starting check_empty_channels loop.")
        self.check_empty_channels.start()

    def cog_unload(self):
        self.check_empty_channels.cancel()
        print("Cancelled check_empty_channels loop.")

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_empty_channels(self):
        print("Running check_empty_channels task.")
        current_time = datetime.datetime.utcnow()
        to_move = []
        for channel_id, empty_since in list(self.empty_voice_channels.items()):
            elapsed = (current_time - empty_since).total_seconds()
            if elapsed >= INACTIVITY_THRESHOLD:
                print(f"Channel ID {channel_id} has been empty for {elapsed} seconds.")
                to_move.append(channel_id)

        for guild in self.bot.guilds:
            hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
            seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
            if not hidden_category or not seen_category:
                print(f"Categories not found in guild {guild.name}.")
                continue

            for channel_id in to_move:
                channel = guild.get_channel(channel_id)
                if channel and channel.category and channel.category.id == seen_category_id:
                    overwrites = channel.overwrites
                    # Deny @everyone the permission to view the channel
                    overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
                    await channel.edit(category=hidden_category, overwrites=overwrites)
                    self.empty_voice_channels.pop(channel_id, None)
                    print(f"Moved {channel.name} back to hidden category and updated permissions.")

    @check_empty_channels.before_loop
    async def before_check_empty_channels(self):
        await self.bot.wait_until_ready()
        print("Bot is ready. Starting check_empty_channels loop.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            print(f"Categories not found in guild {guild.name}.")
            return

        if after.channel and after.channel.id == create_fireteam_channel_id:
            print(f"{member.name} has joined the create_fireteam channel.")
            # Move a voice channel from hidden_category to seen_category
            moved_channel = None
            for channel_id in voice_channels:
                channel = guild.get_channel(channel_id)
                if channel and channel.category and channel.category.id == hidden_category_id:
                    overwrites = channel.overwrites
                    # Allow @everyone to view the channel
                    overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
                    await channel.edit(category=seen_category, overwrites=overwrites)
                    moved_channel = channel
                    print(f"Moved {channel.name} to seen category and updated permissions.")
                    break  # Move only one channel
            if moved_channel:
                # Move the member to the newly moved channel
                await member.move_to(moved_channel)
                print(f"Moved {member.name} to {moved_channel.name}.")

        # Check if any voice channels are empty
        if before.channel and before.channel.id in voice_channels:
            if len(before.channel.members) == 0:
                self.empty_voice_channels[before.channel.id] = datetime.datetime.utcnow()
                print(f"{before.channel.name} is now empty. Starting inactivity timer.")
            else:
                self.empty_voice_channels.pop(before.channel.id, None)
                print(f"{before.channel.name} is no longer empty. Resetting inactivity timer.")

        if after.channel and after.channel.id in voice_channels:
            self.empty_voice_channels.pop(after.channel.id, None)
            print(f"{member.name} joined {after.channel.name}. Resetting inactivity timer if it was set.")

    @nextcord.slash_command(name="tidy_up", description="Manually tidy up voice channels.")
    async def tidy_up(self, interaction: nextcord.Interaction):
        if interaction.user.id not in allowed_user_ids:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.name} attempted to use tidy_up without permission.")
            return

        guild = interaction.guild
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            await interaction.response.send_message("Categories not found.", ephemeral=True)
            print("Categories not found during tidy_up command.")
            return

        for channel_id in voice_channels:
            channel = guild.get_channel(channel_id)
            if channel and channel.category and channel.category.id == seen_category_id:
                overwrites = channel.overwrites
                # Deny @everyone the permission to view the channel
                overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
                await channel.edit(category=hidden_category, overwrites=overwrites)
                self.empty_voice_channels.pop(channel_id, None)
                print(f"Tidied up {channel.name}: moved back to hidden category and updated permissions.")

        await interaction.response.send_message("Voice channels have been tidied up.", ephemeral=True)
        print(f"{interaction.user.name} ran tidy_up command.")

async def setup(bot):
    bot.add_cog(VoiceCog(bot))
    print("VoiceCog has been added to the bot.")