import nextcord
from nextcord.ext import commands

class Rankings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    

def setup(bot):
    bot.add_cog(Rankings(bot))