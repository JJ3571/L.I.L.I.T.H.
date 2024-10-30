# cogs/movies.py
import os

import discord
from discord.ext import commands
from discord import app_commands

import dotenv
import aiohttp

#.env Variable for secret keys
DISCORD_BOT_TOKEN = dotenv.dotenv_values(".env")["DISCORD_BOT_TOKEN"]
OMDB_API_KEY = dotenv.dotenv_values(".env")["OMDB_API_KEY"]
OMDB_API_URL = "http://www.omdbapi.com/?i=tt3896198&apikey="



class MovieCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(self.movie)

    @app_commands.command(name="movie")
    @app_commands.describe(title="Movie title to search for.")
    async def movie(self, interaction: discord.Interaction, title: str):
        await interaction.response.send_message(f"Searching for {title}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OMDB_API_URL}{OMDB_API_KEY}&t={title}") as response:
                movie_data = await response.json()
                print(movie_data)  # Debugging: Print the response data
        
        if movie_data['Response'] == 'True':
            poster = movie_data.get('Poster', None)
            embed = discord.Embed(
                title=movie_data['Title'],
                description=movie_data['Plot'],
                color=discord.Color.blue()
            )
            if poster and poster != 'N/A':
                embed.set_image(url=poster)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("Movie not found")
        
    async def cog_load(self):
        await self.bot.tree.sync()


def setup(bot):
    bot.add_cog(MovieCog(bot))