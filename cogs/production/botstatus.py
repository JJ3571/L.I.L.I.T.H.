import nextcord
from nextcord.ext import commands, tasks
import itertools

from server_configs.config import GUILD_ID
from server_configs.cogs_config import admin_user_ids

class BotStatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status_cycle.start()
        self.status_list = itertools.cycle([
            "Sly 3: Honor Among Thieves",
            "Your Mom",
            "Music",
            "Rocket League"
        ])
        self.current_status = None

    def cog_unload(self):
        self.status_cycle.cancel()
        print("BotStatusCog has been unloaded.")

    @tasks.loop(seconds=30)
    async def status_cycle(self):
        self.current_status = next(self.status_list)
        await self.bot.change_presence(activity=nextcord.Game(name=self.current_status))

    @status_cycle.before_loop
    async def before_status_cycle(self):
        await self.bot.wait_until_ready()
        print("Bot is ready. Starting status_cycle loop.")

    @nextcord.slash_command(name="status", description="Manage the bot's status.")
    async def status(self, interaction: nextcord.Interaction):
        pass

    @status.subcommand(name="set", description="Set the bot's status.")
    async def set_status(self, interaction: nextcord.Interaction, status: str):

        await self.bot.change_presence(activity=nextcord.Game(name=status))
        self.status_cycle.cancel()  # Stop the status cycle when a custom status is set
        await interaction.response.send_message(f"Bot status updated to: {status}", ephemeral=True)
        print(f"Bot status updated to: {status} by {interaction.user.name}")

    @status.subcommand(name="start", description="Start cycling through predefined statuses.")
    async def start_status_cycle(self, interaction: nextcord.Interaction):

        self.status_cycle.start()
        await interaction.response.send_message("Started cycling through predefined statuses.", ephemeral=True)
        print(f"Started status cycle by {interaction.user.name}")

    @status.subcommand(name="stop", description="Stop cycling through predefined statuses.")
    async def stop_status_cycle(self, interaction: nextcord.Interaction):

        self.status_cycle.cancel()
        await interaction.response.send_message("Stopped cycling through predefined statuses.", ephemeral=True)
        print(f"Stopped status cycle by {interaction.user.name}")

async def setup(bot):
    bot.add_cog(BotStatusCog(bot))
    print("BotStatusCog has been added to the bot.")