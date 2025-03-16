import nextcord
from nextcord.ext import commands

class Debug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


    @nextcord.slash_command(name="debug", description="Debugging commands")
    async def debug(self, interaction: nextcord.Interaction):
        embed = nextcord.Embed(title=f"Debug Embed <:mana_u:1350711397088235581>", description=f"This is a debug embed <:mana_u:1350711397088235581>", color=0x00ff00)
        embed.add_field(name=f"Field 1 <:mana_u:1350711397088235581>", value=f"This is an inline field with emoji: <:mana_u:1350711397088235581>", inline=True)
        embed.add_field(name=f"Field 2 <:mana_u:1350711397088235581>", value=f"This is a non-inline field with emoji: <:mana_u:1350711397088235581>", inline=False)
        embed.set_footer(text=f"Footer with emoji: <:mana_u:1350711397088235581>")

        await interaction.response.send_message(embed=embed)

def setup(bot):
    bot.add_cog(Debug(bot))
    print("DebugCog loaded.")