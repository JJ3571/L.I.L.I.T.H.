import nextcord
from nextcord.ext import commands, tasks
import datetime

from server_configs.cogs_config import allowed_user_ids, voice_channel_ids, create_fireteam_channel_id, watch_party_channel_id, watch_party_event_id, seen_category_id, hidden_category_id

# ---------- Controls ---------- #
INACTIVITY_THRESHOLD = 10  # In seconds (1 minute)
INACTIVITY_CHECK_INTERVAL = 10  # In seconds

instant_hide_inactive = False # Set to True to instantly hide inactive channels

WATCH_PARTY_PRE_EVENT = datetime.timedelta(minutes=30)  # Time before event to show channel
WATCH_PARTY_POST_EVENT = datetime.timedelta(hours=2, minutes=30)  # Time after event start to hide channel
WATCH_PARTY_CHECK_INTERVAL = 5 # In minutes

# ---------- VoiceCog ---------- #
class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.empty_voice_channels = {}  # channel_id: timestamp when it became empty
        print("Initializing VoiceCog.")
        self.check_empty_channels.start()
        self.monitor_watch_party.start()

    def cog_unload(self):
        self.check_empty_channels.cancel()
        self.monitor_watch_party.cancel()
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

        for guild in self.bot.guilds:
            hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
            seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
            if not hidden_category or not seen_category:
                print(f"Categories not found in guild '{guild.name}'.")
                continue

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

    @tasks.loop(minutes=WATCH_PARTY_CHECK_INTERVAL)
    async def monitor_watch_party(self):
        print("Running monitor_watch_party task.")
        for guild in self.bot.guilds:
            watch_party_channel = guild.get_channel(watch_party_channel_id)
            if not watch_party_channel:
                print(f"Watch Party channel with ID {watch_party_channel_id} not found in guild '{guild.name}'.")
                continue

            event_active = await self.is_watch_party_event_active(guild)
            hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
            seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)

            if not hidden_category or not seen_category:
                print(f"Categories not found in guild '{guild.name}'.")
                continue

            if event_active and watch_party_channel.category.id == hidden_category_id:
                # Move to seen_category 30 minutes before event
                overwrites = watch_party_channel.overwrites
                overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
                await watch_party_channel.edit(category=seen_category, overwrites=overwrites)
                print(f"Watch Party channel '{watch_party_channel.name}' moved to seen category for the event.")
            elif not event_active and watch_party_channel.category.id == seen_category_id:
                # Move back to hidden_category 2.5 hours after event start
                overwrites = watch_party_channel.overwrites
                overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
                await watch_party_channel.edit(category=hidden_category, overwrites=overwrites)
                print(f"Watch Party channel '{watch_party_channel.name}' moved back to hidden category after the event.")

    @monitor_watch_party.before_loop
    async def before_monitor_watch_party(self):
        await self.bot.wait_until_ready()
        print("Bot is ready. Starting monitor_watch_party loop.")

    async def is_watch_party_event_active(self, guild):
        try:
            event = await guild.fetch_scheduled_event(watch_party_event_id)
            if not event:
                print(f"Watch Party event with ID {watch_party_event_id} not found in guild '{guild.name}'.")
                return False

            event_start = event.start_time  # Assuming start_time is timezone-aware UTC datetime
            current_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

            pre_event_time = event_start - WATCH_PARTY_PRE_EVENT
            post_event_time = event_start + WATCH_PARTY_POST_EVENT

            if pre_event_time <= current_time <= post_event_time:
                print(f"Watch Party event is active in guild '{guild.name}'.")
                return True
            else:
                print(f"Watch Party event is not active in guild '{guild.name}'.")
                return False
        except Exception as e:
            print(f"Error fetching Watch Party event in guild '{guild.name}': {e}")
            return False

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
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
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            print(f"Hidden category not found in guild '{guild.name}'.")
            return

        overwrites = channel.overwrites
        # Deny @everyone the permission to view the channel
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
        await channel.edit(category=hidden_category, overwrites=overwrites)
        print(f"Moved '{channel.name}' to hidden category and updated permissions.")

    @nextcord.slash_command(name="watch_party", description="Manage the Watch Party channel.")
    async def watch_party_group(self, interaction: nextcord.Interaction):
        pass  # This serves as a parent for subcommands

    @watch_party_group.subcommand(name="show", description="Show the Watch Party channel.")
    async def show_watch_party(self, interaction: nextcord.Interaction):
        guild = interaction.guild
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        if not watch_party_channel:
            await interaction.response.send_message("Watch Party channel not found.", ephemeral=True)
            print("Watch Party channel not found during /watch_party show command.")
            return

        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            await interaction.response.send_message("Seen category not found.", ephemeral=True)
            print("Seen category not found during /watch_party show command.")
            return

        overwrites = watch_party_channel.overwrites
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
        await watch_party_channel.edit(category=seen_category, overwrites=overwrites)
        print(f"Watch Party channel '{watch_party_channel.name}' moved to seen category via /watch_party show.")
        await interaction.response.send_message("Watch Party channel has been shown.", ephemeral=True)

    @watch_party_group.subcommand(name="hide", description="Hide the Watch Party channel.")
    async def hide_watch_party(self, interaction: nextcord.Interaction):
        guild = interaction.guild
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        if not watch_party_channel:
            await interaction.response.send_message("Watch Party channel not found.", ephemeral=True)
            print("Watch Party channel not found during /watch_party hide command.")
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            await interaction.response.send_message("Hidden category not found.", ephemeral=True)
            print("Hidden category not found during /watch_party hide command.")
            return

        overwrites = watch_party_channel.overwrites
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
        await watch_party_channel.edit(category=hidden_category, overwrites=overwrites)
        print(f"Watch Party channel '{watch_party_channel.name}' moved to hidden category via /watch_party hide.")
        await interaction.response.send_message("Watch Party channel has been hidden.", ephemeral=True)

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

        for channel_id in voice_channel_ids:
            channel = guild.get_channel(channel_id)
            if channel and channel.category and channel.category.id == seen_category_id:
                overwrites = channel.overwrites
                # Deny @everyone the permission to view the channel
                overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
                await channel.edit(category=hidden_category, overwrites=overwrites)
                self.empty_voice_channels.pop(channel_id, None)
                print(f"Tidied up '{channel.name}': moved back to hidden category and updated permissions.")

        # Also tidy up the Watch Party channel
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        if watch_party_channel and watch_party_channel.category.id != seen_category_id:
            overwrites = watch_party_channel.overwrites
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
            await watch_party_channel.edit(category=seen_category, overwrites=overwrites)
            print(f"Tidied up Watch Party channel '{watch_party_channel.name}': moved to seen category.")

        await interaction.response.send_message("Voice channels have been tidied up.", ephemeral=True)
        print(f"{interaction.user.name} ran tidy_up command.")

async def setup(bot):
    bot.add_cog(VoiceCog(bot))
    print("VoiceCog has been added to the bot.")