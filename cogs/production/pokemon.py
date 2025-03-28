import aiohttp
import nextcord
from nextcord.ext import commands
import sqlite3
import asyncio

from server_configs.cogs_config import admin_user_ids


pkgo_api_url = "https://pogoapi.net/api/v1/"
raid_bosses_key = "raid_bosses.json"

class Pokemon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "pokemon.db"
        self.create_tables()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS friendcodes (
                discord_id INT PRIMARY KEY,
                in_game_name TEXT NOT NULL,
                friend_code TEXT NOT NULL
            )
        ''')

        conn.commit()
        conn.close()

    def add_user(self, discord_id, in_game_name, friend_code):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO friendcodes (discord_id, in_game_name, friend_code) VALUES (?, ?, ?)',
                       (discord_id, in_game_name, friend_code))
        conn.commit()
        conn.close()

    def get_user(self, discord_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT in_game_name, friend_code FROM friendcodes WHERE discord_id = ?', (discord_id,))
        user = cursor.fetchone()
        conn.close()
        return user

    def get_all_users(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT discord_id, in_game_name, friend_code FROM friendcodes')
        users = cursor.fetchall()
        conn.close()
        return users

    @nextcord.slash_command(name="pkgo", description="Parent command for Pokemon Go related commands")
    async def pkgo(self, interaction: nextcord.Interaction):
        pass  # This is the parent command, it won't do anything by itself

    # @pkgo.subcommand(name="raidboss", description="Fetch current raid bosses")
    # async def raidboss(self, interaction: nextcord.Interaction, name: str = None):
    #     await interaction.response.defer()
        
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get(f"{pkgo_api_url+raid_bosses_key}") as response:
    #             raid_boss_data = await response.json()
    #             print(raid_boss_data)  # Debugging: Print the response data
        
    #     current_bosses = raid_boss_data.get('current', {})
    #     previous_bosses = raid_boss_data.get('previous', {})
    #     tiers_to_include = ['5', '6', 'mega']
    #     embeds = []

    #     inline_toggle = False

    #     def create_embed(boss):
    #         embed = nextcord.Embed(
    #             title=f"**{boss['name']}**",  # Bold the name
    #             color=nextcord.Color.red()
    #         )
    #         embed.add_field(name="**Type**", value=", ".join(boss['type']), inline=inline_toggle)
    #         embed.add_field(name="**Boosted Hundo**", value=boss['max_boosted_cp'], inline=inline_toggle)
    #         embed.add_field(name="**Normal Hundo**", value=boss['max_unboosted_cp'], inline=inline_toggle)
    #         return embed

    #     if name:
    #         found = False
    #         for tier, bosses in current_bosses.items():
    #             for boss in bosses:
    #                 if boss['name'].lower() == name.lower():
    #                     embeds.append(create_embed(boss))
    #                     found = True
    #                     break
    #             if found:
    #                 break

    #         if not found:
    #             for tier, bosses in previous_bosses.items():
    #                 for boss in bosses:
    #                     if boss['name'].lower() == name.lower():
    #                         embeds.append(create_embed(boss))
    #                         found = True
    #                         break
    #                 if found:
    #                     break

    #         if not found:
    #             await interaction.followup.send(f"No raid boss found with the name {name}.")
    #             return
    #     else:
    #         for tier in tiers_to_include:
    #             bosses = current_bosses.get(tier, [])
    #             for boss in bosses:
    #                 embeds.append(create_embed(boss))
        
    #     for embed in embeds:
    #         await interaction.followup.send(embed=embed)


    @pkgo.subcommand(name="add-friendcode", description="Add yourself to the Clan friendcode roster!")
    async def adduser(self, interaction: nextcord.Interaction, in_game_name: str, friend_code: str):
        # Remove spaces from the input
        sanitized_friend_code = friend_code.replace(" ", "")

        # Validate that the friend code contains only digits and is exactly 12 characters long
        if not sanitized_friend_code.isdigit() or len(sanitized_friend_code) != 12:
            await interaction.response.send_message(
                "Invalid friend code! Please ensure it contains exactly 12 digits and no letters or special characters.",
                ephemeral=True
            )
            return

        # Store the sanitized friend code (without spaces) in the database
        discord_id = str(interaction.user.id)
        self.add_user(discord_id, in_game_name, sanitized_friend_code)

        # Format the friend code into 4-number chunks for display
        formatted_friend_code = " ".join([sanitized_friend_code[i:i+4] for i in range(0, 12, 4)])

        await interaction.response.send_message(
            f"User {interaction.user.mention} added with in-game name {in_game_name} and friend code `{formatted_friend_code}`"
        )

    @pkgo.subcommand(name="friendcode", description="Displays the IGN and friend code of a user")
    async def user(self, interaction: nextcord.Interaction, user: nextcord.User):
        discord_id = str(user.id)
        user_data = self.get_user(discord_id)
        if user_data:
            in_game_name, friend_code = user_data

            # Format the friend code into 4-number chunks for display
            formatted_friend_code = " ".join([friend_code[i:i+4] for i in range(0, 12, 4)])

            embed = nextcord.Embed(title=f"{user.display_name}'s Friend Code", color=nextcord.Color.red())
            embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
            embed.add_field(name="In-Game Name", value=in_game_name, inline=True)
            embed.add_field(name="Friend Code", value=f"`{formatted_friend_code}`", inline=True)
            await interaction.response.send_message(embed=embed)

        else:
            await interaction.response.send_message(f"No data found for {user.mention}")

    @pkgo.subcommand(name="clan-friendcodes", description="Get a list of all friend codes for the Clan!")
    async def allusers(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        users = self.get_all_users()
        if users:
            for discord_id, in_game_name, friend_code in users:
                formatted_friend_code = " ".join([friend_code[i:i+4] for i in range(0, 12, 4)])
                user = self.bot.get_user(discord_id) #get the discord user object

                embed = nextcord.Embed(color=nextcord.Color.red())
                if user:
                    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else user.default_avatar.url)
                else:
                    embed.set_author(name=f"User ID: {discord_id}") #if user is not found, use their id.
                embed.add_field(name="User", value=f"<@{discord_id}>", inline=True)
                embed.add_field(name="IGN", value=in_game_name, inline=True)
                embed.add_field(name="Code", value=f"`{formatted_friend_code}`", inline=True)

                await interaction.channel.send(embed=embed)
                await asyncio.sleep(1)
            await interaction.response.send_message("Clan friendcodes sent!", ephemeral=True)
        else:
            await interaction.response.send_message("No users found")

    # @pkgo.subcommand(name="admin-add", description="Admin-only: Add a friend code for another user.")
    # async def admin_add(self, interaction: nextcord.Interaction, user: nextcord.User, in_game_name: str, friend_code: str):
    #     # Check if the user is an admin
    #     if interaction.user.id not in admin_user_ids:
    #         await interaction.response.send_message(
    #             "You do not have permission to use this command.", ephemeral=True
    #         )
    #         return

    #     # Remove spaces from the input
    #     sanitized_friend_code = friend_code.replace(" ", "")

    #     # Validate that the friend code contains only digits and is exactly 12 characters long
    #     if not sanitized_friend_code.isdigit() or len(sanitized_friend_code) != 12:
    #         await interaction.response.send_message(
    #             "Invalid friend code! Please ensure it contains exactly 12 digits and no letters or special characters.",
    #             ephemeral=True
    #         )
    #         return

    #     # Store the sanitized friend code (without spaces) in the database
    #     discord_id = str(user.id)
    #     self.add_user(discord_id, in_game_name, sanitized_friend_code)

    #     # Format the friend code into 4-number chunks for display
    #     formatted_friend_code = " ".join([sanitized_friend_code[i:i+4] for i in range(0, 12, 4)])

    #     await interaction.response.send_message(
    #         f"Admin {interaction.user.mention} added {user.mention} with in-game name {in_game_name} and friend code `{formatted_friend_code}`"
    #     )
        
def setup(bot):
    bot.add_cog(Pokemon(bot))
    print("PokemonCog has been added to the bot.")