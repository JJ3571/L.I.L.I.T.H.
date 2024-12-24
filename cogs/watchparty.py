import nextcord
from nextcord.ext import commands, tasks
import datetime, pytz

from server_configs.config import GUILD_ID
from server_configs.cogs_config import watch_party_channel_id, seen_category_id, hidden_category_id

WATCH_PARTY_CHECK_INTERVAL = 5  # In minutes
WATCH_PARTY_EVENT_TIME = datetime.time(hour=18, minute=15)  # 6:15 PM PST
WATCH_PARTY_AUTO_HIDE_TIMEOUT = datetime.timedelta(hours=3)  # 3 hours

class WatchPartyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reserved_channels = {}
        self.reservation_end_time = None
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

        current_time = datetime.datetime.now(pytz.timezone('US/Pacific'))
        if current_time.weekday() == 6 and current_time.time() >= WATCH_PARTY_EVENT_TIME and watch_party_channel.category.id == hidden_category_id:
            seen_category = guild.get_channel(seen_category_id)
            await watch_party_channel.edit(category=seen_category)
            self.reservation_end_time = current_time + WATCH_PARTY_AUTO_HIDE_TIMEOUT
            overwrites = watch_party_channel.overwrites
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
            await watch_party_channel.edit(overwrites=overwrites)
            print(f"Watch Party channel '{watch_party_channel.name}' moved to seen category for the event and reserved until {self.reservation_end_time}.")

        if self.reservation_end_time and current_time < self.reservation_end_time:
            print(f"Watch Party channel '{watch_party_channel.name}' is reserved until {self.reservation_end_time}.")
            return

        if len(watch_party_channel.members) == 0:
            last_message_time = max((message.created_at for message in await watch_party_channel.history(limit=100).flatten()), default=None)
            if last_message_time and (datetime.datetime.now(pytz.utc) - last_message_time) > WATCH_PARTY_AUTO_HIDE_TIMEOUT:
                hidden_category = guild.get_channel(hidden_category_id)
                await watch_party_channel.edit(category=hidden_category)
                print(f"Watch Party channel '{watch_party_channel.name}' moved back to hidden category due to inactivity.")

    @monitor_watch_party.before_loop
    async def before_monitor_watch_party(self):
        await self.bot.wait_until_ready()
        print("Bot is ready. Starting monitor_watch_party loop.")

    @nextcord.slash_command(name="watchparty", description="Manage the watch party channel.")
    async def watchparty(self, interaction: nextcord.Interaction):
        pass

    @watchparty.subcommand(name="show", description="Move the watch party channel to the seen category.")
    async def watchparty_show(self, interaction: nextcord.Interaction):
        guild = self.bot.get_guild(GUILD_ID)
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        seen_category = guild.get_channel(seen_category_id)

        if watch_party_channel and seen_category:
            await interaction.response.defer()
            await watch_party_channel.edit(category=seen_category)
            self.reservation_end_time = datetime.datetime.now(pytz.timezone('US/Pacific')) + WATCH_PARTY_AUTO_HIDE_TIMEOUT
            readable_time = self.reservation_end_time.strftime("%m/%d at %I:%M%p PST")
            readable_time = readable_time.replace("AM", "am").replace("PM", "pm")
            overwrites = watch_party_channel.overwrites
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
            await watch_party_channel.edit(overwrites=overwrites)
            await interaction.followup.send(f"{watch_party_channel.name} reserved until {readable_time}.")
        else:
            await interaction.response.send_message("Failed to move the channel. Please check the configuration.")

    @watchparty.subcommand(name="hide", description="Move the watch party channel to the hidden category.")
    async def watchparty_hide(self, interaction: nextcord.Interaction):
        guild = self.bot.get_guild(GUILD_ID)
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        hidden_category = guild.get_channel(hidden_category_id)

        if watch_party_channel and hidden_category:
            await interaction.response.defer()
            await watch_party_channel.edit(category=hidden_category)
            self.reservation_end_time = None
            await interaction.followup.send(f"{watch_party_channel.name} has been hidden.")
        else:
            await interaction.response.send_message("Failed to move the channel. Please check the configuration.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and before.channel.id == watch_party_channel_id:
            if len(before.channel.members) == 0:
                current_time = datetime.datetime.now(pytz.timezone('US/Pacific'))
                if not self.reservation_end_time or current_time >= self.reservation_end_time:
                    await self.hide_channel(before.channel)

    async def hide_channel(self, channel):
        guild = channel.guild
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            print(f"Hidden category not found in guild '{guild.name}'.")
            return

        overwrites = channel.overwrites
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
        await channel.edit(category=hidden_category, overwrites=overwrites)
        print(f"Moved '{channel.name}' to hidden category and updated permissions.")

async def setup(bot):
    bot.add_cog(WatchPartyCog(bot))
    print("WatchPartyCog has been added to the bot.")