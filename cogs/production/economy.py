import nextcord
from nextcord.ext import commands, tasks
import aiosqlite
import time, datetime
import random
import pytz

from server_configs.config import GUILD_ID
from server_configs.config import backup_channel_id, watch_party_channel_id, admin_user_ids, afk_channel_id, heads_emoji_id, tails_emoji_id, bot_spam_id
from server_configs.database_config import DATABASE_PATHS


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_timers = {}
        self.message_counts = {}
        self.reward_interval = 60  # seconds
        self.voice_reward_amount = 5 # coins
        self.message_reward_amount = 1 # coins
        self.movie_night_reward = 1000 # coins
        self.movie_night_time_threshold = 90 * 60  # 1.5 hours in seconds

        self.leaderboard_items_per_page = 12

        self.db_path = DATABASE_PATHS["economy"]
        self.reward_users.start()
        self.backup_task.start()


    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        balance INTEGER DEFAULT 0
                    )
                ''')
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trust_fund (
                        beneficiary_user_id INTEGER PRIMARY KEY,
                        balance INTEGER DEFAULT 0
                    )
                ''')
            await conn.commit()

    async def get_user_balance(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = await cursor.fetchone()
            return result[0] if result else 0

    async def deduct_user_balance(self, user_id: int, amount: int): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                # First check if user has enough balance
                await cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                result = await cursor.fetchone()
                current_balance = result[0] if result else 0
                
                if current_balance < amount:
                    print(f"DEBUG: Insufficient balance for user {user_id}. Has {current_balance}, needs {amount}")
                    return False
                
                # Deduct the amount
                await cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                print(f"DEBUG: Successfully deducted {amount} coins from user {user_id}")
            await conn.commit()
            return True

    async def update_balance(self, user_id, amount): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
                await cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            await conn.commit()

    async def get_all_balances(self): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC")
                result = await cursor.fetchall() # await fetchall
            return result
    
    # Trust Fund Methods
    async def add_to_trust_fund(self, beneficiary_user_id: int, amount: int):
        """Add money to a user's trust fund"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR IGNORE INTO trust_fund (beneficiary_user_id) VALUES (?)", (beneficiary_user_id,))
                await cursor.execute("UPDATE trust_fund SET balance = balance + ? WHERE beneficiary_user_id = ?", (amount, beneficiary_user_id))
            await conn.commit()
    
    async def get_trust_fund_balance(self, beneficiary_user_id: int):
        """Get the trust fund balance for a user"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT balance FROM trust_fund WHERE beneficiary_user_id = ?", (beneficiary_user_id,))
                result = await cursor.fetchone()
            return result[0] if result else 0
    
    async def withdraw_from_trust_fund(self, beneficiary_user_id: int, amount: int):
        """Withdraw money from a user's trust fund to their regular balance"""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                # Check if trust fund has enough balance
                await cursor.execute("SELECT balance FROM trust_fund WHERE beneficiary_user_id = ?", (beneficiary_user_id,))
                result = await cursor.fetchone()
                current_balance = result[0] if result else 0
                
                if current_balance < amount:
                    return False  # Not enough in trust fund
                
                # Deduct from trust fund and add to regular balance
                await cursor.execute("UPDATE trust_fund SET balance = balance - ? WHERE beneficiary_user_id = ?", (amount, beneficiary_user_id))
                await cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (beneficiary_user_id,))
                await cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, beneficiary_user_id))
            await conn.commit()
            return True

    @tasks.loop(minutes=1)
    async def backup_task(self):
        # Make sure datetime is used correctly if it wasn't before
        await self.create_tables()
        now = datetime.datetime.now(pytz.timezone('US/Pacific'))
        if now.hour in [0, 12] and now.minute == 0:
            await self.bot.wait_until_ready()
            channel = self.bot.get_channel(backup_channel_id)
            if channel:
                try:
                    await channel.send(file=nextcord.File(self.db_path))
                    print("Backup task completed.")
                except Exception as e:
                    print(f"Backup task failed to send file: {e}")
            else:
                print(f"Backup channel not found with ID: {backup_channel_id}. Backup failed.")

    @backup_task.before_loop
    async def before_backup_task(self):
        await self.bot.wait_until_ready()
        await self.create_tables()
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

        # Helper to safely encode names for printing
        def s_print(name_str: str) -> str:
            return name_str.encode('ascii', 'replace').decode('ascii')

        # Helper to determine if a channel is eligible for earning rewards
        def is_rewardable_channel(channel: nextcord.VoiceChannel) -> bool:
            if channel is None:
                return False
            if channel.id == afk_channel_id:  # AFK channel is not rewardable
                return False
            if "💧" in channel.name:  # Water channels are not rewardable
                return False
            return True # Otherwise, it's rewardable

        # --- Scenario 1: User JOINS a voice channel (was not in one before) ---
        if before.channel is None and after.channel is not None:
            if is_rewardable_channel(after.channel):
                self.voice_timers[user_id] = time.time()
                print(f"Economy: Started voice timer for {s_print(member.display_name)} in rewardable channel {s_print(after.channel.name)}")
            else:
                print(f"Economy: User {s_print(member.display_name)} joined non-rewardable channel {s_print(after.channel.name)}. No timer started.")

        # --- Scenario 2: User LEAVES a voice channel (is not in one after) ---
        elif before.channel is not None and after.channel is None:
            print(f"Economy: User {s_print(member.display_name)} left voice channel {s_print(before.channel.name)}")
            if user_id in self.voice_timers:  # Check if a timer was active
                if is_rewardable_channel(before.channel):  # Only process if they left a rewardable channel
                    elapsed_time = time.time() - self.voice_timers[user_id]
                    print(f"Economy: Elapsed time for {s_print(member.display_name)} in {s_print(before.channel.name)}: {elapsed_time:.2f}s")
                    
                    intervals_completed = int(elapsed_time / self.reward_interval)
                    if intervals_completed > 0:
                        reward_amount = intervals_completed * self.voice_reward_amount
                        await self.update_balance(user_id, reward_amount) # Added await
                        print(f"Economy: Rewarded {reward_amount} coins to {s_print(member.display_name)} for voice activity in {s_print(before.channel.name)}.")
                else:
                    print(f"Economy: User {s_print(member.display_name)} left non-rewardable channel {s_print(before.channel.name)} while timer was active. Timer cleared without reward.")
                del self.voice_timers[user_id]  # Clear timer regardless of reward, as they left.
                print(f"Economy: Timer removed for {s_print(member.display_name)} (left channel).")
            else:
                print(f"Economy: User {s_print(member.display_name)} left {s_print(before.channel.name)}, no active timer found.")

        # --- Scenario 3: User SWITCHES voice channels ---
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            print(f"Economy: User {s_print(member.display_name)} switched from {s_print(before.channel.name)} to {s_print(after.channel.name)}")

            # Action 1: If they had an active timer and were in a rewardable 'before' channel, process rewards.
            if user_id in self.voice_timers:
                if is_rewardable_channel(before.channel):
                    elapsed_time = time.time() - self.voice_timers[user_id]
                    print(f"Economy: Elapsed time for {s_print(member.display_name)} in {s_print(before.channel.name)} (switched): {elapsed_time:.2f}s")
                    
                    intervals_completed = int(elapsed_time / self.reward_interval)
                    if intervals_completed > 0:
                        reward_amount = intervals_completed * self.voice_reward_amount
                        await self.update_balance(user_id, reward_amount) # Added await
                        print(f"Economy: Rewarded {reward_amount} coins to {s_print(member.display_name)} for activity in {s_print(before.channel.name)}.")
                else: 
                    print(f"Economy: User {s_print(member.display_name)} switched from non-rewardable {s_print(before.channel.name)} while timer was active. Timer cleared without reward from 'before' channel.")
                del self.voice_timers[user_id] 
                print(f"Economy: Old timer removed for {s_print(member.display_name)} (switched).")

            # Action 2: If they moved TO a rewardable 'after' channel, start a new timer.
            if is_rewardable_channel(after.channel):
                self.voice_timers[user_id] = time.time()
                print(f"Economy: Started new voice timer for {s_print(member.display_name)} in rewardable channel {s_print(after.channel.name)} (switched).")
            else: 
                print(f"Economy: User {s_print(member.display_name)} switched to non-rewardable channel {s_print(after.channel.name)}. No new timer started.")

    @tasks.loop(seconds=60)
    async def reward_users(self):
        await self.create_tables()
        # Process message rewards
        if self.message_counts:
            print(f"Processing message rewards for {len(self.message_counts)} users...")
        for user_id, count in list(self.message_counts.items()):
            if count > 0:
                reward_amount = count * self.message_reward_amount
                await self.update_balance(user_id, reward_amount)
                # print(f"Rewarded {reward_amount} coins to {user_id} for messages.") # Optional: make this debug print
        self.message_counts.clear()
        if self.message_counts:
            print("Message counts cleared.")

        # Note: Voice rewards are handled on voice state update (on user leaving a channel)
        # If you wanted rewards for *staying* in voice, you'd need a different timer/tracking approach here.


    @nextcord.slash_command(name="econ", description="Economy commands", guild_ids=[GUILD_ID])
    async def econ(self, interaction: nextcord.Interaction):
        pass

    @econ.subcommand(name="balance", description="Check your balance or someone else's")
    async def balance_command(self, interaction: nextcord.Interaction, member: nextcord.Member = nextcord.SlashOption(required=False, description='The member to check the balance of.')):
        member = member or interaction.user
        balance = await self.get_user_balance(member.id)

        embed = nextcord.Embed(title=f"🪙  {balance}", color=nextcord.Color.blue())
        embed.set_author(name=member.display_name, icon_url=member.avatar.url if member.avatar else member.default_avatar.url)

        await interaction.response.send_message(embed=embed)


    @econ.subcommand(name="give", description="Give currency to another user")
    async def give_command(self, interaction: nextcord.Interaction, member: nextcord.Member, amount: int, reason: str = nextcord.SlashOption(required=False, description='Reason for the transaction')):
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return

        sender_id = interaction.user.id

        if sender_id in admin_user_ids:
            # Use AdminGiveView as defined below (assuming it's outside the Cog or defined later)
            # If AdminGiveView is defined inside the Cog, access it as Economy.AdminGiveView
            view = AdminGiveView(self, member, amount, reason)
            await interaction.response.send_message("Give from your balance or the treasury?", view=view, ephemeral=True)
            return

        sender_balance = await self.get_user_balance(sender_id)
        if sender_balance < amount:
            await interaction.response.send_message("Insufficient funds.", ephemeral=True)
            return

        await self.update_balance(sender_id, -amount)
        await self.update_balance(member.id, amount)
        embed = nextcord.Embed(
                    title="Transaction Successful",
                    description=f"{interaction.user.mention} gave {member.mention} {amount} 🪙."+(f"\n\n**Reason:** {reason}" if reason else ""),
                    color=nextcord.Color.green()
                )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Sender", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Recipient", value=member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{amount} 🪙", inline=True)

        await interaction.response.send_message(embed=embed)

    @econ.subcommand(name="tax", description="[Admin] Tax a user, removing currency from their balance.")
    async def tax_command(self, 
                          interaction: nextcord.Interaction, 
                          member: nextcord.Member, 
                          amount: int, 
                          reason: str = nextcord.SlashOption(required=True, description='Reason for the tax.')):
        
        # Check if the command issuer is an admin
        if interaction.user.id not in admin_user_ids:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        # Amount must be positive
        if amount <= 0:
            await interaction.response.send_message("Amount to tax must be positive.", ephemeral=True)
            return

        # Cannot tax bots
        if member.bot:
            await interaction.response.send_message("You cannot tax a bot.", ephemeral=True)
            return
        
        # Cannot tax oneself
        if member == interaction.user:
            await interaction.response.send_message("You cannot tax yourself.", ephemeral=True)
            return

        # Perform the deduction using update_balance with a negative amount
        await self.update_balance(member.id, -amount)
        
        taxed_user_new_balance = await self.get_user_balance(member.id)

        # Create confirmation embed
        embed = nextcord.Embed(
            title="EXECUTIVE TARIFF!🧑‍⚖️",
            description=f"{member.mention} has been taxed {amount} 🪙 by {interaction.user.mention}.",
            color=nextcord.Color.orange() 
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Taxed User", value=member.mention, inline=True)
        embed.add_field(name="Amount Taxed", value=f"{amount} 🪙", inline=True)
        embed.add_field(name="New Balance", value=f"{taxed_user_new_balance} 🪙", inline=True)
        
        cleaned_reason = reason.strip() if reason and reason.strip() else None
        if cleaned_reason:
            embed.add_field(name="Reason", value=cleaned_reason, inline=False)
        
        await interaction.response.send_message(embed=embed)

        # Send notification to bot_spam channel
        bot_spam_channel = self.bot.get_channel(bot_spam_id)
        if bot_spam_channel:
            spam_embed = nextcord.Embed(
                title="EXECUTIVE TARIFF!🧑‍⚖️",
                description=f"{interaction.user.mention} taxed {member.mention} for {amount} 🪙 in {interaction.channel.mention}.",
                color=nextcord.Color.dark_red()
            )
            spam_embed.add_field(name="Admin", value=f"{interaction.user.mention}", inline=True)
            spam_embed.add_field(name="Taxed User", value=f"{member.mention}", inline=True)
            spam_embed.add_field(name="Amount", value=str(amount), inline=True)
            if cleaned_reason:
                spam_embed.add_field(name="Reason", value=cleaned_reason, inline=False)
            spam_embed.set_footer(text=f"Channel: #{interaction.channel.name} | Taxed User New Balance: {taxed_user_new_balance}")
            try:
                await bot_spam_channel.send(embed=spam_embed)
            except Exception as e:
                print(f"Failed to send 'tax' notification to bot_spam channel: {e}")

    @econ.subcommand(name="request", description="Request currency from another user")
    async def receive_command(self, interaction: nextcord.Interaction, member: nextcord.Member, amount: int, reason: str = nextcord.SlashOption(required=False, description='Reason for the request')):
        if amount <= 0:
            await interaction.response.send_message("Amount must be positive.", ephemeral=True)
            return
        
        if member == interaction.user:
            await interaction.response.send_message("You cannot request money from yourself.", ephemeral=True)
            return

        if member.bot:
            await interaction.response.send_message("You cannot request money from a bot.", ephemeral=True)
            return

        # Create the view instance
        # Pass self.bot (the bot instance) and bot_spam_id
        view = ReceiveRequestView(self, interaction.user, member, amount, reason, self.bot, bot_spam_id)

        # Create the initial request embed
        embed = nextcord.Embed(
            title="Incoming Payment Request",
            description=f"{interaction.user.mention} is requesting {amount} 🪙 from you, {member.mention}.",
            color=nextcord.Color.orange() 
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Requester", value=interaction.user.mention, inline=True)
        embed.add_field(name="Target", value=member.mention, inline=True)
        embed.add_field(name="Amount", value=f"{amount} 🪙", inline=True)
        
        cleaned_reason = reason.strip() if reason and reason.strip() else None
        if cleaned_reason:
            embed.add_field(name="Reason", value=cleaned_reason, inline=False)
        embed.set_footer(text="Please respond using the buttons below.")

        # Send the interactive message to the current channel
        await interaction.response.send_message(embed=embed, view=view)
        # Set the message object on the view for timeout handling
        view.message = await interaction.original_message()


        # Send a notification to bot_spam_id channel
        bot_spam_channel = self.bot.get_channel(bot_spam_id)
        if bot_spam_channel:
            spam_embed = nextcord.Embed(
                title="Payment Request Initiated",
                description=f"{interaction.user.mention} requested {amount} 🪙 from {member.mention} in {interaction.channel.mention}.",
                color=nextcord.Color.dark_orange()
            )
            spam_embed.add_field(name="Requester", value=f"{interaction.user.mention}", inline=True)
            spam_embed.add_field(name="Requestee", value=f"{member.mention}", inline=True)
            spam_embed.add_field(name="Amount", value=str(amount), inline=True)
            if cleaned_reason:
                spam_embed.add_field(name="Reason", value=cleaned_reason, inline=False)
            spam_embed.set_footer(text=f"Channel: #{interaction.channel.name}")
            try:
                await bot_spam_channel.send(embed=spam_embed)
            except Exception as e:
                print(f"Failed to send 'receive' request notification to bot_spam channel: {e}")
       


    class LeaderboardPageButton(nextcord.ui.Button):
        def __init__(self, label, direction):
            super().__init__(label=label, style=nextcord.ButtonStyle.primary)
            self.direction = direction

        async def callback(self, interaction: nextcord.Interaction):
            # Defer immediately as fetching users and editing the message takes time
            await interaction.response.defer()
            self.view.current_page += self.direction
            self.view.update_buttons()
            await self.view.send_page(interaction) # send_page handles editing the message

    class LeaderboardView(nextcord.ui.View):
        def __init__(self, bot, leaderboard_data, items_per_page):
            # leaderboard_data is a list of (user_id, balance) tuples
            super().__init__(timeout=180) # Add a timeout
            self.bot = bot
            self.leaderboard_data = leaderboard_data # Store the raw data
            self.items_per_page = items_per_page
            self.current_page = 0
            self.total_items = len(leaderboard_data)
            # Calculate max_page index (0-based)
            self.max_page = (self.total_items - 1) // self.items_per_page if self.total_items > 0 else 0

            # Store the message object to edit it later
            self._message = None

            self.update_buttons()

        def update_buttons(self):
            self.clear_items()
            if self.current_page > 0:
                self.add_item(Economy.LeaderboardPageButton(label="Previous", direction=-1))
            if self.current_page < self.max_page:
                self.add_item(Economy.LeaderboardPageButton(label="Next", direction=1))

        async def send_page(self, interaction: nextcord.Interaction):
            """Builds and sends/edits the embed for the current page."""
            print(f"[DEBUG] send_page: Entered. Interaction ID: {interaction.id}, Channel ID: {interaction.channel_id}") # DEBUG
            start = self.current_page * self.items_per_page
            end = start + self.items_per_page
            page_data_slice = self.leaderboard_data[start:end]

            description_lines = []
            # print(f"[DEBUG] send_page: Processing {len(page_data_slice)} items for page {self.current_page}") # DEBUG - Optional
            for i, (user_id, balance) in enumerate(page_data_slice):
                rank = start + i + 1
                user = self.bot.get_user(user_id)
                if user is None:
                    try:
                        # print(f"[DEBUG] send_page: Fetching user {user_id}") # DEBUG - Optional
                        user = await self.bot.fetch_user(user_id)
                    except nextcord.errors.NotFound:
                        user = None
                    except Exception as e:
                        print(f"[DEBUG] send_page: Error fetching user {user_id}: {e}") # DEBUG
                        user = None

                if user:
                    description_lines.append(f"{rank}. {user.mention}: `{balance}` 🪙")
                else:
                    description_lines.append(f"{rank}. Unknown User (ID: {user_id}): `{balance}` 🪙")

            description = "\n".join(description_lines) or "No users on this page."

            embed = nextcord.Embed(title="Leaderboard", description=description, color=nextcord.Color.blue())
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.max_page + 1} | Total Users: {self.total_items}")
            print(f"[DEBUG] send_page: Embed created. Title: '{embed.title}', Desc length: {len(embed.description or '')}") # DEBUG

            try:
                if self._message is None:
                    print(f"[DEBUG] send_page: _message is None. Attempting interaction.followup.send(). Interaction responded: {interaction.response.is_done()}") # DEBUG
                    self._message = await interaction.followup.send(embed=embed, view=self)
                    print(f"[DEBUG] send_page: interaction.followup.send() successful. Message ID: {self._message.id}") # DEBUG
                else:
                    print(f"[DEBUG] send_page: _message exists (ID: {self._message.id}). Attempting self._message.edit()") # DEBUG
                    await self._message.edit(embed=embed, view=self)
                    print(f"[DEBUG] send_page: self._message.edit() successful.") # DEBUG
            except nextcord.errors.NotFound as nf_err:
                print(f"[DEBUG] send_page: nextcord.errors.NotFound caught: {nf_err}") # DEBUG
                self.stop()
            except Exception as e:
                print(f"[DEBUG] send_page: Generic Exception caught: {type(e).__name__} - {e}") # DEBUG
                import traceback
                traceback.print_exc() # DEBUG
                try:
                    print(f"[DEBUG] send_page: Attempting to send ephemeral error message via followup.") # DEBUG
                    # Check if interaction is done; it should be after defer()
                    if interaction.response.is_done():
                        await interaction.followup.send("An error occurred while updating the leaderboard. Please try again.", ephemeral=True)
                        print(f"[DEBUG] send_page: Ephemeral error message sent via followup.") # DEBUG
                    else:
                        # This path is unlikely if defer() worked but included for completeness
                        print(f"[DEBUG] send_page: Interaction not done, attempting response.send_message for error.") # DEBUG
                        await interaction.response.send_message("An error occurred while updating the leaderboard. Please try again.", ephemeral=True)
                        print(f"[DEBUG] send_page: Ephemeral error message sent via response.send_message.") # DEBUG
                except Exception as e_followup:
                    print(f"[DEBUG] send_page: Exception sending ephemeral error message: {type(e_followup).__name__} - {e_followup}") # DEBUG
                    import traceback
                    traceback.print_exc() # DEBUG
            print(f"[DEBUG] send_page: Exiting.") # DEBUG

        async def on_timeout(self):
            """Disables buttons when the view times out."""
            print("Leaderboard view timed out.")
            for item in self.children:
                item.disabled = True

            # Try to edit the original message to disable buttons
            if self._message:
                 try:
                      await self._message.edit(view=self)
                      print("Leaderboard message buttons disabled on timeout.")
                 except nextcord.errors.NotFound:
                      print("Leaderboard message not found to disable buttons on timeout.")
                 except Exception as e:
                      print(f"Error disabling leaderboard buttons on timeout: {e}")


    @econ.subcommand(name="leaderboard", description="Display the leaderboard of user balances")
    async def leaderboard_command(self, interaction: nextcord.Interaction):
        """Displays the economy leaderboard with pagination."""
        print(f"'/leaderboard' command triggered by {interaction.user.display_name}")
        try:
            await interaction.response.defer()
            print("Leaderboard interaction deferred.")

            # Get all balances from the database (efficient)
            # This returns a list of (user_id, balance) tuples, already sorted
            all_user_balances = await self.get_all_balances()
            print(f"Fetched {len(all_user_balances)} balances from the database.")

            if not all_user_balances:
                await interaction.followup.send("No users found in the leaderboard.", ephemeral=True)
                print("Sent 'no users' message.")
                return

            # Create the paginated view
            # Pass the full list of (user_id, balance) tuples and the items per page
            view = self.LeaderboardView(self.bot, all_user_balances, self.leaderboard_items_per_page)
            print("LeaderboardView created.")

            # Send the first page using the view's send_page method
            # This will handle fetching users for the first page and sending/editing the response
            await view.send_page(interaction)
            print("Initial leaderboard page sent.")

        except Exception as e:
            print(f"An error occurred in the leaderboard command: {e}")
            # Use traceback for more detailed error logging in the console
            import traceback
            traceback.print_exc()
            # Send an error message to the user using followup (since we deferred)
            try:
                if interaction.response.is_done():
                     await interaction.followup.send("An error occurred while generating the leaderboard.")
                else: # Fallback just in case defer failed somehow
                     await interaction.response.send_message("An error occurred while generating the leaderboard.", ephemeral=True)
                print("Sent error message to user.")
            except Exception as send_error:
                print(f"Failed to send error message to user: {send_error}")

    @econ.subcommand(name="trustfund", description="[JJ/Nut Only] Check trust fund balance or withdraw from trust fund")
    async def trustfund_command(self, interaction: nextcord.Interaction, 
                               action: str = nextcord.SlashOption(choices=["balance", "withdraw"], description="Check balance or withdraw"),
                               amount: int = nextcord.SlashOption(required=False, description="Amount to withdraw (only for withdraw action)")):
        # Only allow JJ3571 and TheGiftedNut to use this command
        allowed_users = [321888250136363009, 220656152994643969]  # JJ3571 and TheGiftedNut user IDs
        if interaction.user.id not in allowed_users:
            await interaction.response.send_message("This command is only available to JJ3571 and TheGiftedNut.", ephemeral=True)
            return

        if action == "balance":
            trust_balance = await self.get_trust_fund_balance(interaction.user.id)
            embed = nextcord.Embed(
                title="🏦 Trust Fund Balance",
                description=f"Your trust fund contains **{trust_balance}** 🪙",
                color=nextcord.Color.gold()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        elif action == "withdraw":
            if amount is None or amount <= 0:
                await interaction.response.send_message("Please specify a valid amount to withdraw.", ephemeral=True)
                return
            
            trust_balance = await self.get_trust_fund_balance(interaction.user.id)
            if trust_balance < amount:
                await interaction.response.send_message(f"Insufficient trust fund balance. You have {trust_balance} 🪙 available.", ephemeral=True)
                return
            
            success = await self.withdraw_from_trust_fund(interaction.user.id, amount)
            if success:
                new_balance = await self.get_user_balance(interaction.user.id)
                new_trust_balance = await self.get_trust_fund_balance(interaction.user.id)
                embed = nextcord.Embed(
                    title="🏦 Trust Fund Withdrawal",
                    description=f"Successfully withdrew **{amount}** 🪙 from your trust fund!",
                    color=nextcord.Color.green()
                )
                embed.add_field(name="New Regular Balance", value=f"{new_balance} 🪙", inline=True)
                embed.add_field(name="Remaining Trust Fund", value=f"{new_trust_balance} 🪙", inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message("Withdrawal failed. Please try again.", ephemeral=True)
    
class AdminGiveView(nextcord.ui.View):
    def __init__(self, cog, member, amount,reason):
        super().__init__(timeout=60) # Add a timeout
        self.cog = cog
        self.member = member
        self.amount = amount
        self.reason = reason if reason else None

    @nextcord.ui.button(label="From Balance", style=nextcord.ButtonStyle.green)
    async def from_balance(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer() # Defer interaction
        sender_id = interaction.user.id
        sender_balance = await self.cog.get_user_balance(sender_id)
        if sender_balance < self.amount:
            await interaction.followup.send("Insufficient funds.", ephemeral=True)
            self.stop() # Stop the view
            return
        await self.cog.update_balance(sender_id, -self.amount)
        await self.cog.update_balance(self.member.id, self.amount)

        embed = nextcord.Embed(
            title="Transaction Successful",
            description=f"{interaction.user.mention} gave {self.member.mention} {self.amount} 🪙."+(f"\n\n**Reason:**\n{self.reason}" if self.reason else ""),
            color=nextcord.Color.green()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Sender", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Recipient", value=self.member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{self.amount} 🪙", inline=True)

        await interaction.followup.send(embed=embed) # Use followup after defer
        self.stop()

    @nextcord.ui.button(label="From Treasury", style=nextcord.ButtonStyle.blurple)
    async def from_treasury(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer() # Defer interaction
        await self.cog.update_balance(self.member.id, self.amount)
        embed = nextcord.Embed(
            title="Treasury Transaction Successful",
            description=f"{interaction.user.mention} added {self.amount} 🪙 to {self.member.mention} from the treasury.",
            color=nextcord.Color.blue()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Recipient", value=self.member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{self.amount} 🪙", inline=True)

        await interaction.followup.send(embed=embed) # Use followup after defer
        self.stop()

    async def on_timeout(self):
        # Disable buttons when the view times out
        for item in self.children:
            item.disabled = True
        # For ephemeral views, no need to edit the message as it disappears for the user anyway.
        pass

class ReceiveRequestView(nextcord.ui.View):
    def __init__(self, cog: Economy, requester: nextcord.Member, requestee: nextcord.Member, amount: int, reason: str, bot: nextcord.Client, bot_spam_channel_id: int):
        super().__init__(timeout=300) # 5-minute timeout
        self.cog = cog
        self.requester = requester
        self.requestee = requestee
        self.amount = amount
        self.reason_text = reason.strip() if reason and reason.strip() else None
        self.bot = bot
        self.bot_spam_channel_id = bot_spam_channel_id
        self.message: nextcord.Message = None # Will be set after the initial message is sent

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        """Checks if the user interacting is the requestee, or the requester trying to cancel."""
        if interaction.user.id == self.requestee.id:
            return True
        if interaction.user.id == self.requester.id and interaction.data.get('custom_id') == 'deny_request':
            return True # Requester can only press "Deny" to cancel
        
        await interaction.response.send_message("This request is not for you, or you cannot perform this action.", ephemeral=True)
        return False

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, nextcord.ui.Button):
                item.disabled = True

    async def send_bot_spam_update(self, title: str, description: str, color: nextcord.Color):
        bot_spam_channel = self.bot.get_channel(self.bot_spam_channel_id)
        if bot_spam_channel:
            embed = nextcord.Embed(title=title, description=description, color=color)
            embed.set_footer(text=f"Original request by: {self.requester.display_name} to {self.requestee.display_name} for {self.amount} 🪙.")
            try:
                await bot_spam_channel.send(embed=embed)
            except Exception as e:
                print(f"Failed to send receive update to bot_spam: {e}")

    @nextcord.ui.button(label="Pay", style=nextcord.ButtonStyle.green, custom_id="pay_request")
    async def pay_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # interaction_check ensures this is the requestee
        await interaction.response.defer()

        requestee_balance = self.cog.get_user_balance(self.requestee.id)
        if requestee_balance < self.amount:
            await interaction.followup.send(f"You do not have sufficient funds ({requestee_balance} 🪙) to pay {self.amount} 🪙.", ephemeral=True)
            return # Keep the request active

        # Process payment
        await self.cog.update_balance(self.requestee.id, -self.amount)
        await self.cog.update_balance(self.requester.id, self.amount)

        success_embed = nextcord.Embed(
            title="Payment Successful",
            description=f"{self.requestee.mention} paid {self.requester.mention} {self.amount} 🪙.",
            color=nextcord.Color.green()
        )
        success_embed.set_author(name=self.requestee.display_name, icon_url=self.requestee.avatar.url if self.requestee.avatar else self.requestee.default_avatar.url)
        if self.reason_text:
            success_embed.add_field(name="Reason", value=self.reason_text, inline=False)
        success_embed.add_field(name="Payer", value=self.requestee.mention, inline=True)
        success_embed.add_field(name="Recipient", value=self.requester.mention, inline=True)
        success_embed.add_field(name="Amount", value=f"{self.amount} 🪙", inline=True)
        
        self.disable_all_buttons()
        await interaction.message.edit(embed=success_embed, view=self)
        await self.send_bot_spam_update("Payment Request Paid", f"{self.requestee.mention} paid {self.amount} 🪙 to {self.requester.mention}.", nextcord.Color.green())
        self.stop()

    @nextcord.ui.button(label="Deny", style=nextcord.ButtonStyle.red, custom_id="deny_request")
    async def deny_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        
        denial_description = ""
        if interaction.user.id == self.requester.id:
            denial_description = f"{self.requester.mention} cancelled the request for {self.amount} 🪙 from {self.requestee.mention}."
            await interaction.followup.send("You have cancelled the request.", ephemeral=True) # Confirmation for requester
        else: # Denied by requestee
            denial_description = f"{self.requestee.mention} denied the request for {self.amount} 🪙 from {self.requester.mention}."
            # No ephemeral message needed for requestee, main message will update.

        denied_embed = nextcord.Embed(
            title="Payment Request Denied",
            description=denial_description,
            color=nextcord.Color.red()
        )
        denied_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        if self.reason_text:
            denied_embed.add_field(name="Original Reason", value=self.reason_text, inline=False)
        
        self.disable_all_buttons()
        await interaction.message.edit(embed=denied_embed, view=self)
        await self.send_bot_spam_update("Payment Request Denied/Cancelled", denial_description, nextcord.Color.red())
        self.stop()

    async def on_timeout(self):
        if self.message:
            timeout_embed = nextcord.Embed(
                title="Payment Request Timed Out",
                description=f"The request from {self.requester.mention} to {self.requestee.mention} for {self.amount} coins has timed out.",
                color=nextcord.Color.greyple()
            )
            if self.reason_text:
                timeout_embed.add_field(name="Original Reason", value=self.reason_text, inline=False)
            
            self.disable_all_buttons()
            try:
                await self.message.edit(embed=timeout_embed, view=self)
                await self.send_bot_spam_update("Payment Request Timed Out", f"Request from {self.requester.mention} to {self.requestee.mention} for {self.amount} coins timed out.", nextcord.Color.greyple())
            except nextcord.errors.NotFound:
                print(f"ReceiveRequest: Original message (ID: {self.message.id}) not found on timeout.")
            except Exception as e:
                print(f"ReceiveRequest: Error updating message on timeout: {e}")
        self.stop()


async def setup(bot):
    cog = Economy(bot)
    await cog.create_tables()
    bot.add_cog(Economy(bot))
    print("EconomyCog has been added to the bot.")