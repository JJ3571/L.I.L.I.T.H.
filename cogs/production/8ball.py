import nextcord
from nextcord.ext import commands
import random

from server_configs.config import GUILD_ID
class Magic8Ball(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.responses = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes – definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful."
        ]

    @nextcord.slash_command(name="8ball", description="Ask the magic 8-ball", guild_ids=[GUILD_ID])
    async def eight_ball(self, interaction: nextcord.Interaction, question: str):
        response = random.choice(self.responses)
        embed = nextcord.Embed(color=0x3749CE)
        embed.add_field(name="Question: ", value=question, inline=False)
        embed.add_field(name="🎱 Answer: ", value=response, inline=False)
        await interaction.response.send_message(embed=embed)


def setup(bot):
    bot.add_cog(Magic8Ball(bot))