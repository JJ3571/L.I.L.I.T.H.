import os

import discord 
from discord import app_commands
from discord.ext import commands

from dotenv import dotenv_values, load_dotenv
import aiohttp

# - - - - - - - - Configs - - - - - - - -


# Bot configuration
bot = commands.Bot(command_prefix='.', intents=discord.Intents.all())

# .env configuration
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
OMDB_API_KEY = os.getenv('OMDB_API_KEY')

# OMDB API Config
OMDB_API_URL = "http://www.omdbapi.com/?i=tt3896198&apikey="
OMDB_API_POSTER_URL = "http://img.omdbapi.com/?i=tt3896198&h=600&apikey="

# - - - - - - - - Events - - - - - - - -

@bot.event
async def on_ready():
    print(f'Bot is ready and running.')
    try:
        synced = await bot.tree.sync()
        print(f"Commands synced: {len(synced)}")
    except Exception as e:
        print(f"Error syncing commands:\n{e}")

# - - - - - - - - Slash Commands - - - - - - - -

@bot.tree.command(name="movie")
@app_commands.describe(title="Movie title to search for.")
async def say(interaction: discord.Interaction, title: str):
    await interaction.response.send_message(f"Searching for {title}...")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OMDB_API_URL}{OMDB_API_KEY}&t={title}") as response:
            movie_data = await response.json()
            print(movie_data)  # Debugging: Print the response data
    
    if movie_data['Response'] == 'True':
        poster = movie_data.get('Poster', None) #Better fetching of Movie poster vs separate API call
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


@bot.tree.command(name="hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello {interaction.user.mention}!", 
    ephemeral=True)


# - - - - - - - - Run the Bot - - - - - - - -
bot.run(DISCORD_BOT_TOKEN)