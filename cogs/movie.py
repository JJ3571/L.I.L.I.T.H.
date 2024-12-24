import aiohttp
import nextcord
from nextcord.ext import commands

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
            imdb_url = f"https://www.imdb.com/title/{movie_data['imdbID']}/"
            embed = nextcord.Embed(
                title=movie_data['Title'],
                description=movie_data['Plot'],
                color=nextcord.Color.blue(),
                url=imdb_url
            )
            embed.add_field(name="Release Date", value=movie_data['Released'], inline=True)
            embed.add_field(name="Runtime", value=movie_data['Runtime'], inline=True)
            embed.add_field(name="Genre", value=movie_data['Genre'], inline=True)
            embed.add_field(name="Director", value=movie_data['Director'], inline=True)
            embed.add_field(name="Awards", value=movie_data['Awards'], inline=True)
            
            ratings = movie_data.get('Ratings', [])
            for rating in ratings:
                embed.add_field(name=rating['Source'], value=rating['Value'], inline=True)
            
            embed.add_field(name="Metascore", value=movie_data['Metascore'], inline=True)
            embed.add_field(name="IMDB Rating", value=movie_data['imdbRating'], inline=True)
            
            poster = movie_data.get('Poster', None)
            if poster and poster != 'N/A':
                embed.set_image(url=poster)
            
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Movie not found")

async def setup(bot):
    bot.add_cog(MovieCog(bot))