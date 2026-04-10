import nextcord
from nextcord.ext import commands

from main_bot.server_configs.config import GUILD_ID

class Rankings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    

def setup(bot):
    bot.add_cog(Rankings(bot))