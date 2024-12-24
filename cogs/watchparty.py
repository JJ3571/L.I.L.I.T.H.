import nextcord
from nextcord.ext import commands, tasks
import datetime

from server_configs.config import GUILD_ID
from server_configs.cogs_config import watch_party_channel_id, watch_party_event_id, seen_category_id, hidden_category_id

WATCH_PARTY_PRE_EVENT = datetime.timedelta(minutes=30)  # Time before event to show channel
WATCH_PARTY_POST_EVENT = datetime.timedelta(hours=2, minutes=30)  # Time after event start to hide channel
WATCH_PARTY_CHECK_INTERVAL = 5  # In minutes

class WatchPartyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("Initializing WatchPartyCog.")
        self.monitor_watch_party.start()

    def cog_unload(self):
        self.monitor_watch_party.cancel()
        print("WatchPartyCog has been unloaded.")

    @tasks.loop(minutes=WATCH_PARTY_CHECK_INTERVAL)
    async def monitor_watch_party(self):
        print("Running monitor_watch_party task.")
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print(f"Guild with ID {GUILD_ID} not found.")
            return

        watch_party_channel = guild.get_channel(watch_party_channel_id)
        if not watch_party_channel:
            print(f"Watch Party channel with ID {watch_party_channel_id} not found in guild '{guild.name}'.")
            return

        event_active = await self.is_watch_party_event_active(guild)
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)

        if not hidden_category or not seen_category:
            print(f"Categories not found in guild '{guild.name}'.")
            return

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

    @nextcord.slash_command(name="watch_party", description="Manage the Watch Party channel.")
    async def watch_party_group(self, interaction: nextcord.Interaction):
        pass  # This serves as a parent for subcommands

    @watch_party_group.subcommand(name="show", description="Show the Watch Party channel.")
    async def show_watch_party(self, interaction: nextcord.Interaction):
        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

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
        if guild.id != GUILD_ID:
            return

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

async def setup(bot):
    bot.add_cog(WatchPartyCog(bot))
    print("WatchPartyCog has been added to the bot.")
    