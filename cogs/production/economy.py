import nextcord
from nextcord.ext import commands, tasks
import sqlite3
import time, datetime
import random
import pytz

from server_configs.cogs_config import backup_channel_id, watch_party_channel_id, admin_user_ids, afk_channel_id, heads_emoji_id, tails_emoji_id

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_timers = {}
        self.message_counts = {}
        self.reward_interval = 60  # seconds
        self.voice_reward_amount = 5
        self.message_reward_amount = 1
        self.movie_night_reward = 1000
        self.movie_night_time_threshold = 90 * 60  # 1.5 hours in seconds

        self.db_path = "economy.db"
        self.create_tables()
        self.reward_users.start()
        self.backup_task.start()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()

    def get_user_balance(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0

    def deduct_user_balance(self, user_id: int, amount: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

    def update_balance(self, user_id, amount):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

    def get_all_balances(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC")
        result = cursor.fetchall()
        conn.close()
        
        balances = {user_id: balance for user_id, balance in result} 
        return balances

    @tasks.loop(minutes=1)
    async def backup_task(self):
        now = datetime.now(pytz.timezone('US/Pacific'))
        if now.hour in [0, 12] and now.minute == 0:
            await self.bot.wait_until_ready()
            channel = self.bot.get_channel(backup_channel_id)
            if channel:
                await channel.send(file=nextcord.File(self.db_path))
                print("Backup task completed.")

    @backup_task.before_loop
    async def before_backup_task(self):
        await self.bot.wait_until_ready()
        print("Backup task is ready to start.")


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        user_id = message.author.id
        if user_id not in self.message_counts:
            self.message_counts[user_id] = 0
        self.message_counts[user_id] += 1

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        user_id = member.id

        if before.channel is None and after.channel is not None:
            # User joined a voice channel
            self.voice_timers[user_id] = time.time()

        elif before.channel is not None and after.channel is None:
            # User left a voice channel
            if user_id in self.voice_timers:
                elapsed_time = time.time() - self.voice_timers[user_id]
                del self.voice_timers[user_id]

                if before.channel.id != afk_channel_id:
                    # Reward regular voice activity
                    self.update_balance(user_id, int(elapsed_time / self.reward_interval) * self.voice_reward_amount)

                if before.channel.id == watch_party_channel_id and elapsed_time >= self.movie_night_time_threshold:
                    # Reward for movie night attendance
                    self.update_balance(user_id, self.movie_night_reward)
                    try:
                        await member.send("You were rewarded 1000 coins for attending movie night!")
                    except nextcord.HTTPException:
                        print(f"Failed to send DM to {member.name}")

    @tasks.loop(seconds=60)
    async def reward_users(self):
        for user_id, count in self.message_counts.items():
            self.update_balance(user_id, count * self.message_reward_amount)
        self.message_counts.clear()

    @nextcord.slash_command(name="balance", description="Check your balance or someone else's")
    async def balance_command(self, interaction: nextcord.Interaction, member: nextcord.Member = nextcord.SlashOption(required=False, description='The member to check the balance of.')):
        member = member or interaction.user
        balance = self.get_user_balance(member.id)
        
        embed = nextcord.Embed(title=f"🪙  {balance}", color=nextcord.Color.blue())
        embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else member.default_avatar.url)
        
        await interaction.response.send_message(embed=embed)


    @nextcord.slash_command(name="give", description="Give currency to another user")
    async def give_command(self, interaction: nextcord.Interaction, member: nextcord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        sender_id = interaction.user.id

        if sender_id in admin_user_ids:
            view = AdminGiveView(self, member, amount)
            await interaction.response.send_message("Give from your balance or the treasury?", view=view, ephemeral=True)
            return

        sender_balance = self.get_user_balance(sender_id)
        if sender_balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        self.update_balance(sender_id, -amount)
        self.update_balance(member.id, amount)
        embed = nextcord.Embed(
                title="Transaction Successful",
                description=f"{interaction.user.mention} gave {member.mention} {amount} coins.",
                color=nextcord.Color.green()
            )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Sender", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Recipient", value=member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{amount} coins", inline=True)

        await interaction.response.send_message(embed=embed)


    class LeaderboardPageButton(nextcord.ui.Button):
        def __init__(self, label, direction):
            super().__init__(label=label, style=nextcord.ButtonStyle.primary)
            self.direction = direction

        async def callback(self, interaction: nextcord.Interaction):
            await interaction.response.defer()  # Defer the interaction response
            self.view.current_page += self.direction
            self.view.update_buttons()
            await self.view.send_page(interaction)

    class LeaderboardView(nextcord.ui.View):
        def __init__(self, bot, leaderboard):
            super().__init__()
            self.bot = bot
            self.leaderboard = leaderboard
            self.current_page = 0
            self.max_page = (len(leaderboard) - 1) // 5
            self.update_buttons()

        def update_buttons(self):
            self.clear_items()
            if self.current_page > 0:
                self.add_item(Economy.LeaderboardPageButton(label="Previous", direction=-1))
            if self.current_page < self.max_page:
                self.add_item(Economy.LeaderboardPageButton(label="Next", direction=1))

        async def send_page(self, interaction):
            start = self.current_page * 5
            end = start + 5
            page = self.leaderboard[start:end]
            description = "\n".join([f"{user.mention}: `{points}` dabloons" for user, points in page])
            embed = nextcord.Embed(title="Leaderboard", description=description, color=nextcord.Color.blue())
            try:
                if interaction.response.is_done():
                    await interaction.edit_original_message(embed=embed, view=self)
                else:
                    await interaction.followup.send(embed=embed, view=self)
            except nextcord.errors.NotFound:
                print("Interaction not found or already responded to.")

    @nextcord.slash_command(name="leaderboard", description="Display the leaderboard of user balances")
    async def leaderboard_command(self, interaction: nextcord.Interaction):
        try:
            await interaction.response.defer()  # Defer the response to avoid timing out

            balances = self.get_all_balances()
            if not balances:
                await interaction.followup.send("No users found in the leaderboard.", ephemeral=True)
                return

            leaderboard = []
            for user_id, balance in balances.items():
                try:
                    user = await self.bot.fetch_user(user_id)
                    leaderboard.append((user, balance))
                except Exception as e:
                    print(f"Error fetching user {user_id}: {e}")

            leaderboard.sort(key=lambda x: x[1], reverse=True)
            view = self.LeaderboardView(self.bot, leaderboard)
            await view.send_page(interaction)
        except Exception as e:
            print(f"Error in leaderboard_command: {e}")
            await interaction.followup.send("An error occurred while fetching the leaderboard.", ephemeral=True)
            
        
class AdminGiveView(nextcord.ui.View):
    def __init__(self, cog, member, amount):
        super().__init__()
        self.cog = cog
        self.member = member
        self.amount = amount

    @nextcord.ui.button(label="From Balance", style=nextcord.ButtonStyle.green)
    async def from_balance(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        sender_id = interaction.user.id
        sender_balance = self.cog.get_user_balance(sender_id)
        if sender_balance < self.amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return
        self.cog.update_balance(sender_id, -self.amount)
        self.cog.update_balance(self.member.id, self.amount)

        embed = nextcord.Embed(
            title="Transaction Successful",
            description=f"{interaction.user.mention} gave {self.member.mention} {self.amount} coins from their balance.",
            color=nextcord.Color.green()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Sender", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Recipient", value=self.member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{self.amount} coins", inline=True)

        await interaction.response.send_message(embed=embed)
        self.stop()

    @nextcord.ui.button(label="From Treasury", style=nextcord.ButtonStyle.blurple)
    async def from_treasury(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.cog.update_balance(self.member.id, self.amount)
        embed = nextcord.Embed(
            title="Treasury Transaction Successful",
            description=f"{interaction.user.mention} added {self.amount} coins to {self.member.mention} from the treasury.",
            color=nextcord.Color.blue()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Recipient", value=self.member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{self.amount} coins", inline=True)

        await interaction.response.send_message(embed=embed)
        self.stop()

async def setup(bot):
    bot.add_cog(Economy(bot))
    print("EconomyCog has been added to the bot.")