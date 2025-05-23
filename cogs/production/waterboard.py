import nextcord
from nextcord.ext import commands, tasks
import asyncio
import time
import sqlite3

from server_configs.config import GUILD_ID
from server_configs.cogs_config import seen_category_id, bot_spam_id, admin_user_ids
from cogs.production.economy import Economy

class WaterboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "waterboard.db"
        self.create_tables()
        self.channel_creation_lock = asyncio.Lock()
        self.cooldown_multiplier = 2
        self.waterboard_cost = 200
        self.cleanup_exempt_users.start()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS waterboarded_users (
                user_id INTEGER PRIMARY KEY,
                last_waterboarded_time REAL,
                usage_count INTEGER DEFAULT 0,
                total_waterboarded INTEGER DEFAULT 0,
                total_coins_spent INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS temp_channels (
                channel_id INTEGER PRIMARY KEY
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exempt_users (
                user_id INTEGER PRIMARY KEY,
                exempt_until REAL
            )
        ''')
        conn.commit()
        conn.close()

    def get_last_waterboarded_time(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT last_waterboarded_time FROM waterboarded_users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def update_last_waterboarded_time(self, user_id, timestamp):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time) VALUES (?, ?)", (user_id, timestamp))
        conn.commit()
        conn.close()

    def add_temp_channel(self, channel_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO temp_channels (channel_id) VALUES (?)", (channel_id,))
        conn.commit()
        conn.close()

    def get_temp_channels(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id FROM temp_channels")
        result = cursor.fetchall()
        conn.close()
        return [row[0] for row in result]

    def delete_temp_channel(self, channel_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM temp_channels WHERE channel_id = ?", (channel_id,))
        conn.commit()
        conn.close()


    @nextcord.slash_command(name="executivepardon", description="[Admin] Grant exemption from waterboarding for a set time.",guild_ids=[GUILD_ID])
    async def executivepardon(self, 
                              interaction: nextcord.Interaction, 
                              user: nextcord.Member, 
                              duration: int = nextcord.SlashOption(name="hours", 
                                                                   description="Duration in hours", 
                                                                   default=1, 
                                                                   required=True)):
        if interaction.user.id not in admin_user_ids:
            embed = nextcord.Embed(
                title="Permission Denied",
                description="You do not have permission to use this command.",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        exempt_until = time.time() + (duration * 3600)  # Convert hours to seconds
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO exempt_users (user_id, exempt_until) VALUES (?, ?)", (user.id, exempt_until))
        conn.commit()
        conn.close()

        embed = nextcord.Embed(
            title="Executive Pardon",
            description=f"{user.mention} has been pardoned for {duration} hours.",
            color=nextcord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tasks.loop(minutes=10)
    async def cleanup_exempt_users(self):
        await self.bot.wait_until_ready()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_time = time.time()
        cursor.execute("DELETE FROM exempt_users WHERE exempt_until < ?", (current_time,))
        conn.commit()
        conn.close()


    @nextcord.slash_command(name="waterboard", description="Waterboard a user",guild_ids=[GUILD_ID])
    async def waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member):
        print(f"User id: {interaction.user.id} used the waterboard command on {user.name}.")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if the user is exempt
        cursor.execute("SELECT exempt_until FROM exempt_users WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()
        if result:
            exempt_until = result[0]
            if time.time() < exempt_until:
                conn.close()
                embed = nextcord.Embed(
                    title="Exempt User",
                    description=f"{user.mention} is exempt from waterboarding until <t:{int(exempt_until)}:F>.",
                    color=nextcord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Get the last waterboarded time, usage count, total waterboarded, and total coins spent
        current_time = time.time()
        cursor.execute("SELECT last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent FROM waterboarded_users WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()

        if result:
            last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent = result
            # Reset usage count if more than 30 minutes have passed
            if current_time - last_waterboarded_time > 1800:  # 30 minutes in seconds
                usage_count = 0
        else:
            last_waterboarded_time = 0
            usage_count = 0
            total_waterboarded = 0
            total_coins_spent = 0

        # Calculate the cost using self.waterboard_cost and self.cooldown_multiplier
        cost = self.waterboard_cost * (self.cooldown_multiplier ** usage_count)

        # Check if the user can afford the cost
        economy_cog = self.bot.get_cog('Economy')
        if not economy_cog:
            conn.close()
            embed = nextcord.Embed(title="Error", description="Economy cog is not available.", color=nextcord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        balance = await economy_cog.get_user_balance(interaction.user.id)
        if balance < cost:
            conn.close()
            embed = nextcord.Embed(
                title="Insufficient Funds",
                description=f"You need {cost} coins to waterboard {user.mention}. Your current balance is {balance} coins.",
                color=nextcord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Deduct the cost and update usage count, total waterboarded, and total coins spent
        await economy_cog.deduct_user_balance(interaction.user.id, cost)
        usage_count += 1
        total_waterboarded += 1
        total_coins_spent += cost
        cursor.execute(
            "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
            (user.id, current_time, usage_count, total_waterboarded, total_coins_spent)
        )
        conn.commit()
        conn.close()

        # Notify the user of the successful purchase
        embed = nextcord.Embed(
            title="Waterboard Purchased",
            description=f"You have successfully waterboarded {user.mention} for {cost} coins. The next usage will cost {self.waterboard_cost * (self.cooldown_multiplier ** usage_count)} coins.",
            color=nextcord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Proceed with the waterboarding process
        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            embed = nextcord.Embed(title="Error", description="Seen category not found.", color=nextcord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=False)
            return

        # Start the waterboarding process in a separate task
        asyncio.create_task(self.waterboard_user(interaction, user, seen_category))
        

    @nextcord.slash_command(name="waterboard-ranks", description="All time waterboard rankings.",guild_ids=[GUILD_ID])
    async def leaderboard(self, interaction: nextcord.Interaction):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Fetch the top 10 users with the most waterboards
        cursor.execute("SELECT user_id, total_waterboarded, total_coins_spent FROM waterboarded_users ORDER BY total_waterboarded DESC LIMIT 10")
        results = cursor.fetchall()
        conn.close()

        if not results:
            embed = nextcord.Embed(
                title="Leaderboard",
                description="No waterboard data available.",
                color=nextcord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Build the leaderboard embed
        embed = nextcord.Embed(
            title="Waterboard Leaderboard",
            description="Top 10 users who have been waterboarded the most.",
            color=nextcord.Color.gold()
        )
        for rank, (user_id, total_waterboarded, total_coins_spent) in enumerate(results, start=1):
            user = self.bot.get_user(user_id)
            username = user.name if user else f"User ID: {user_id}"
            embed.add_field(
                name=f"#{rank} - {username}",
                value=f"Waterboarded: {total_waterboarded} times\nCoins Spent: {total_coins_spent}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=False)

        
    async def create_temp_channels(self, guild, seen_category):
        async with self.channel_creation_lock:
            temp_channel_ids = self.get_temp_channels()
            if not temp_channel_ids:
                water_names = [
                    "💧🌊💧🌊", "🌊🐟🌊💧", "💧💧💧🏞️", "💧🐟💧🐟", "💧💧🐟💧",
                    "🐟💧💧🌊", "💧💧💧💧", "💧🏝️💧💧", "🌊💧💧💧", "💧💧🐟🌊"
                ]
                for name in water_names:
                    channel = await guild.create_voice_channel(name, category=seen_category)
                    self.add_temp_channel(channel.id)


    async def delete_temp_channels(self):
        await asyncio.sleep(1)
        temp_channel_ids = self.get_temp_channels()
        for channel_id in temp_channel_ids:
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete()
                    self.delete_temp_channel(channel_id)
                    print("Deleted a temporary channel.")
                except nextcord.errors.NotFound:
                    print("Channel not found for deletion.")
                except Exception as e:
                    print(f"Unexpected error while deleting channel: {e}")


    async def waterboard_user(self, interaction: nextcord.Interaction, user: nextcord.Member, seen_category):
        guild = interaction.guild
        bot_spam_channel = interaction.guild.get_channel(bot_spam_id)
        original_channel_id = user.voice.channel.id if user.voice else None

        try:
            await self.create_temp_channels(guild, seen_category)
            temp_channel_ids = self.get_temp_channels()
            # Ensure the user is in a voice channel before proceeding
            if not user.voice or user.voice.channel is None:
                print(f"{user.name} is not in a voice channel.")
                embed = nextcord.Embed(
                    title="Error",
                    description=f"{user.mention} is not in a voice channel. Waterboarding cannot proceed.",
                    color=nextcord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Move the user through the temporary channels
            for channel_id in temp_channel_ids:
                channel = self.bot.get_channel(channel_id)
                if not user.voice or user.voice.channel is None:
                    print(f"{user.name} disconnected or moved out of voice channel.")
                    break
                print(f"Moving {user.name} to a temporary channel.")
                await user.move_to(channel)
                await asyncio.sleep(1)  # Delay to simulate the waterboarding process

            # Move the user back to the original channel
            if user.voice and original_channel_id:
                print(f"Moving {user.name} back to the original channel.")
                original_channel = self.bot.get_channel(original_channel_id)
                if original_channel:
                    await user.move_to(original_channel)
                    print(f"{user.name} has been moved back to the original channel.")
                else:
                    print(f"Original channel not found for {user.name}.")
            else:
                print(f"{user.name} is not in a voice channel or original channel is not available.")
        except Exception as e:
            print(f"Error during waterboarding {user.name}: {e}")
        finally:
            print(f"Removed {user.name} from active waterboards.")

            # Send a follow-up message
            try:
                embed = nextcord.Embed(
                    description=f"{user.mention} was waterboarded by {interaction.user.mention}.",
                    color=nextcord.Color.blue()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                if bot_spam_channel:
                    await bot_spam_channel.send(embed=embed)
            except nextcord.errors.NotFound:
                print(f"Error: Interaction not found for follow-up message for {user.name}.")

            # Clean up temporary channels
            asyncio.create_task(self.delete_temp_channels())


async def setup(bot):
    bot.add_cog(WaterboardCog(bot))
    print("WaterboardCog has been added to the bot.")