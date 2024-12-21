# cogs/movies.py
import nextcord
from nextcord.ext import commands
import os
import aiohttp

from server_configs.cogs_config import OMDB_API_KEY, OMDB_API_URL 

class MovieCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="movie", description="Search for a movie")
    async def movie(self, interaction: nextcord.Interaction, title: str):
        await interaction.response.send_message(f"Searching for {title}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OMDB_API_URL}{OMDB_API_KEY}&t={title}") as response:
                movie_data = await response.json()
                print(movie_data)  # Debugging: Print the response data
        
        if movie_data['Response'] == 'True':
            poster = movie_data.get('Poster', None)
            embed = nextcord.Embed(
                title=movie_data['Title'],
                description=movie_data['Plot'],
                color=nextcord.Color.blue()
            )
            if poster and poster != 'N/A':
                embed.set_image(url=poster)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Movie not found")

async def setup(bot):
    bot.add_cog(MovieCog(bot))