import nextcord
from nextcord.ext import commands, tasks
import asyncio
import time
import sqlite3

from server_configs.config import GUILD_ID
from server_configs.cogs_config import seen_category_id, bot_spam_id, admin_user_ids
from cogs.economy import Economy

class WaterboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "waterboard.db"
        self.create_tables()
        self.channel_creation_lock = asyncio.Lock()
        self.cooldown_multiplier = 2
        self.waterboard_cost = 100
        self.cleanup_exempt_users.start()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS waterboarded_users (
                user_id INTEGER PRIMARY KEY,
                last_waterboarded_time REAL
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


    @nextcord.slash_command(name="executivepardon", description="Grant a user an exemption from waterboarding.")
    async def executivepardon(self, interaction: nextcord.Interaction, user: nextcord.Member, duration: int):
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


    @nextcord.slash_command(name="waterboard", description="Waterboard a user")
    async def waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member):
        print(f"User id: {interaction.user.id} used the waterboard command on {user.name}.")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT exempt_until FROM exempt_users WHERE user_id = ?", (user.id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            exempt_until = result[0]
            if time.time() < exempt_until:
                embed = nextcord.Embed(
                    title="Exempt User",
                    description=f"{user.mention} is exempt from waterboarding until <t:{int(exempt_until)}:F>.",
                    color=nextcord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        current_time = time.time()
        last_waterboarded_time = self.get_last_waterboarded_time(user.id)
        if last_waterboarded_time and current_time - last_waterboarded_time < 60:
            # User is on cooldown, check if they want to purchase usage
            cost = self.waterboard_cost * self.cooldown_multiplier
            economy_cog = self.bot.get_cog('Economy')
            if not economy_cog:
                embed = nextcord.Embed(title="Error", description="Economy cog is not available.", color=nextcord.Color.red())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            balance = economy_cog.get_user_balance(interaction.user.id)
            if balance < cost:
                embed = nextcord.Embed(title="Cooldown", description=f"{user.mention} has been waterboarded recently. You need {cost} coins to bypass the cooldown.", color=nextcord.Color.orange())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Deduct the cost and double the cost for the next usage
            economy_cog.deduct_user_balance(interaction.user.id, cost)
            self.waterboard_cost *= self.cooldown_multiplier
            embed = nextcord.Embed(title="Waterboard Purchased", description=f"You have purchased a waterboard for {cost} coins. The next usage will cost {self.waterboard_cost * 2} coins.", color=nextcord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            # Reset the cost if the user is not on cooldown
            self.waterboard_cost = 100

        self.update_last_waterboarded_time(user.id, current_time)
        
        # Defer the response only if no response has been sent yet
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)
        
        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            embed = nextcord.Embed(title="Error", description="Seen category not found.", color=nextcord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=False)
            return

        # Start the waterboarding process in a separate task
        asyncio.create_task(self.waterboard_user(interaction, user, seen_category))


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

            for channel_id in temp_channel_ids:
                channel = self.bot.get_channel(channel_id)
                if not user.voice or user.voice.channel is None:
                    print(f"{user.name} disconnected or moved out of voice channel.")
                    break
                print(f"Moving {user.name} to a temporary channel.")
                await user.move_to(channel)
                await asyncio.sleep(1)
            
            if user.voice and original_channel_id:
                print(f"Moving {user.name} back to the original channel.")
                attempts = 0
                max_attempts = 5  # Increase the number of attempts
                while user.voice.channel.id != original_channel_id and attempts < max_attempts:
                    original_channel = self.bot.get_channel(original_channel_id)
                    await user.move_to(original_channel)
                    await asyncio.sleep(1)  # Small delay before checking again
                    attempts += 1
                    print(f"Attempt {attempts}: Checking if {user.name} is in the original channel.")
                if user.voice.channel.id == original_channel_id:
                    print(f"{user.name} is now in the original channel.")
                else:
                    print(f"Failed to move {user.name} to the original channel after {max_attempts} attempts.")
            else:
                print(f"{user.name} is not in a voice channel or original channel is not available.")
        except Exception as e:
            print(f"Error during waterboarding {user.name}: {e}")
        finally:
            print(f"Removed {user.name} from active waterboards.")

            # Ensure the follow-up message is sent even if an error occurs
            try:
                embed = nextcord.Embed(
                    description=f"{user.mention} was waterboarded by {interaction.user.mention}.",
                    color=nextcord.Color.blue()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                await bot_spam_channel.send(embed=embed)
            except nextcord.errors.NotFound:
                print(f"Error: Interaction not found for follow-up message for {user.name}.")

            asyncio.create_task(self.delete_temp_channels())


async def setup(bot):
    bot.add_cog(WaterboardCog(bot))
    print("WaterboardCog has been added to the bot.")