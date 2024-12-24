# original/working
import nextcord
from nextcord.ext import commands, tasks
import datetime

from server_configs.config import GUILD_ID
from server_configs.cogs_config import allowed_user_ids, voice_channel_ids, create_fireteam_channel_id, seen_category_id, hidden_category_id

# ---------- Controls ---------- #
INACTIVITY_THRESHOLD = 10  # In seconds (1 minute)
INACTIVITY_CHECK_INTERVAL = 10  # In seconds

instant_hide_inactive = True # Set to True to instantly hide inactive channels

# ---------- VoiceCog ---------- #
class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.empty_voice_channels = {}  # channel_id: timestamp when it became empty
        print("Initializing VoiceCog.")
        self.check_empty_channels.start()

    def cog_unload(self):
        self.check_empty_channels.cancel()
        print("VoiceCog has been unloaded.")

    @tasks.loop(seconds=INACTIVITY_CHECK_INTERVAL)
    async def check_empty_channels(self):
        if instant_hide_inactive:
            print("Instant hide inactive is enabled; skipping scheduled inactivity checks.")
            return

        print("Running check_empty_channels task.")
        current_time = datetime.datetime.utcnow()
        to_move = []
        for channel_id, empty_since in list(self.empty_voice_channels.items()):
            elapsed = (current_time - empty_since).total_seconds()
            if elapsed >= INACTIVITY_THRESHOLD:
                print(f"Channel ID {channel_id} has been empty for {elapsed} seconds.")
                to_move.append(channel_id)

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print(f"Guild with ID {GUILD_ID} not found.")
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            print(f"Categories not found in guild '{guild.name}'.")
            return

        for channel_id in to_move:
            channel = guild.get_channel(channel_id)
            if channel and channel.category and channel.category.id == seen_category_id:
                overwrites = channel.overwrites
                # Deny @everyone the permission to view the channel
                overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
                await channel.edit(category=hidden_category, overwrites=overwrites)
                self.empty_voice_channels.pop(channel_id, None)
                print(f"Moved '{channel.name}' back to hidden category and updated permissions.")

    @check_empty_channels.before_loop
    async def before_check_empty_channels(self):
        await self.bot.wait_until_ready()
        print("Bot is ready. Starting check_empty_channels loop.")

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
            if len(before.channel.members) == 0:
                if instant_hide_inactive:
                    print(f"'{before.channel.name}' is now empty. Instantly hiding the channel.")
                    await self.hide_channel(before.channel)
                else:
                    self.empty_voice_channels[before.channel.id] = datetime.datetime.utcnow()
                    print(f"'{before.channel.name}' is now empty. Starting inactivity timer.")
            else:
                if not instant_hide_inactive:
                    self.empty_voice_channels.pop(before.channel.id, None)
                print(f"'{before.channel.name}' is no longer empty. Resetting inactivity timer.")

        if after.channel and after.channel.id in voice_channel_ids:
            if not instant_hide_inactive:
                self.empty_voice_channels.pop(after.channel.id, None)
            print(f"{member.name} joined '{after.channel.name}'. Resetting inactivity timer if it was set.")

    async def hide_channel(self, channel):
        guild = channel.guild
        if guild.id != GUILD_ID:
            return

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
        if interaction.user.id not in allowed_user_ids:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            print(f"{interaction.user.name} attempted to use tidy_up without permission.")
            return

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            await interaction.response.send_message("Categories not found.", ephemeral=True)
            print("Categories not found during tidy_up command.")
            return

        for channel_id in voice_channel_ids:
            channel = guild.get_channel(channel_id)
            if channel and channel.category and channel.category.id == seen_category_id:
                overwrites = channel.overwrites
                # Deny @everyone the permission to view the channel
                overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
                await channel.edit(category=hidden_category, overwrites=overwrites)
                self.empty_voice_channels.pop(channel_id, None)
                print(f"Tidied up '{channel.name}': moved back to hidden category and updated permissions.")

        await interaction.response.send_message("Voice channels have been tidied up.", ephemeral=True)
        print(f"{interaction.user.name} ran tidy_up command.")

async def setup(bot):
    bot.add_cog(VoiceCog(bot))
    print("VoiceCog has been added to the bot.")