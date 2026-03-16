import aiohttp
import nextcord
from nextcord.ext import commands

from server_configs.config import GUILD_ID
from server_configs.config import OMDB_API_KEY, OMDB_API_URL

class MovieCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="movie", description="Search for a movie", guild_ids=[GUILD_ID])
    async def movie(self, interaction: nextcord.Interaction, title: str):
        await interaction.response.defer()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OMDB_API_URL}{OMDB_API_KEY}&t={title}") as response:
                movie_data = await response.json()
                print(movie_data)  # Debugging: Print the response data
        
        if movie_data['Response'] == 'True':
            imdb_url = f"https://www.imdb.com/title/{movie_data['imdbID']}/"
            embed = nextcord.Embed(
                title=f"**{movie_data['Title']}**",  # Bold the title
                description=f"**Plot**\n{movie_data['Plot']}",
                color=nextcord.Color.blue(),
                url=imdb_url
            )
            embed.set_thumbnail(url=movie_data.get('Poster', ''))  # Add a thumbnail
            
            # Add fields with bold headers
            embed.add_field(name="**Release Date**", value=movie_data['Released'], inline=True)
            embed.add_field(name="**Runtime**", value=movie_data['Runtime'], inline=True)
            embed.add_field(name="**Genre**", value=movie_data['Genre'], inline=True)
            embed.add_field(name="**Director**", value=movie_data['Director'], inline=True)
            embed.add_field(name="**Awards**", value=movie_data['Awards'], inline=False)
            
            # Add ratings
            ratings = movie_data.get('Ratings', [])
            ratings_str = ""
            if ratings:
                ratings_str = "\n".join([f"{rating['Source']}: {rating['Value']}" for rating in ratings])
            ratings_str += f"\nMetascore: {movie_data['Metascore']}"
            ratings_str += f"\nIMDB Rating: {movie_data['imdbRating']}"

            embed.add_field(name="**Ratings**", value=ratings_str, inline=False)
            
            
            # Add poster as image if available
            poster = movie_data.get('Poster', None)
            if poster and poster != 'N/A':
                embed.set_image(url=poster)
            
            # Add footer
            embed.set_footer(text="Movie information provided by OMDB API")
                    
            # Add poster as image if available
            poster = movie_data.get('Poster', None)
            if poster and poster != 'N/A':
                embed.set_image(url=poster)
            
            # Add footer
            embed.set_footer(text="Movie information provided by OMDB API")
            
            await interaction.followup.send(embed=embed)

async def setup(bot):
    bot.add_cog(MovieCog(bot))