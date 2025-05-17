import nextcord
from nextcord.ext import commands, tasks
import sqlite3
import time, datetime
import random
import pytz

# Assuming server_configs.cogs_config exists and contains necessary IDs
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

        # Define the number of items per page for the leaderboard
        self.leaderboard_items_per_page = 12

        self.db_path = "economy.db"
        self.create_tables()
        # Ensure tasks are started after bot is ready or handle errors
        # reward_users and backup_task are started in __init__, they should use before_loop to wait
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
        # This method is efficient as it only queries the database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Select user_id and balance, ordered by balance DESC
        cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC")
        result = cursor.fetchall() # Returns a list of (user_id, balance) tuples
        conn.close()

        # Return the list of tuples directly, no need to convert to dict here for the leaderboard
        return result


    @tasks.loop(minutes=1)
    async def backup_task(self):
        # Make sure datetime is used correctly if it wasn't before
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

        # User joined a non-AFK voice channel
        if before.channel is None and after.channel is not None and after.channel.id != afk_channel_id:
             self.voice_timers[user_id] = time.time()
             print(f"Started voice timer for {member.display_name} in {after.channel.name}")


        # User left a voice channel
        elif before.channel is not None and after.channel is None:
             print(f"User {member.display_name} left voice channel {before.channel.name}")
             # Only process if they were in a non-AFK channel AND had a timer
             if before.channel.id != afk_channel_id and user_id in self.voice_timers:
                 elapsed_time = time.time() - self.voice_timers[user_id]
                 print(f"Elapsed time for {member.display_name}: {elapsed_time:.2f}s")
                 del self.voice_timers[user_id]
                 print(f"Timer removed for {member.display_name}.")

                 # Reward regular voice activity
                 intervals_completed = int(elapsed_time / self.reward_interval)
                 if intervals_completed > 0:
                      reward_amount = intervals_completed * self.voice_reward_amount
                      self.update_balance(user_id, reward_amount)
                      print(f"Rewarded {reward_amount} coins to {member.display_name} for voice activity.")


                #  # Check for movie night attendance reward
                #  if before.channel.id == watch_party_channel_id and elapsed_time >= self.movie_night_time_threshold:
                #       self.update_balance(user_id, self.movie_night_reward)
                #       print(f"Rewarded {self.movie_night_reward} coins to {member.display_name} for movie night.")
                #       try:
                #           await member.send("You were rewarded 1000 coins for attending movie night!")
                #       except nextcord.HTTPException:
                #           print(f"Failed to send movie night reward DM to {member.name}")
             elif user_id in self.voice_timers:
                  # User left a channel but was in AFK channel or timer wasn't valid for reward processing, just clean up timer
                  print(f"User {member.display_name} left channel {before.channel.name}, but timer not processed for rewards. Cleaning up timer.")
                  del self.voice_timers[user_id]


        # User switched channels
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            print(f"User {member.display_name} switched channel from {before.channel.name} to {after.channel.name}")
            # If leaving a non-AFK channel for a non-AFK channel, stop timer and start a new one (optional - could just let timer run)
            # A simpler logic is to only track entry to non-AFK and process on *leave* (as above).
            # If leaving AFK for non-AFK, start timer.
            if before.channel.id == afk_channel_id and after.channel.id != afk_channel_id:
                 print(f"User {member.display_name} left AFK for non-AFK. Starting timer.")
                 self.voice_timers[user_id] = time.time()
            # If leaving non-AFK for AFK, stop timer and process reward for time spent in non-AFK
            elif before.channel.id != afk_channel_id and after.channel.id == afk_channel_id and user_id in self.voice_timers:
                 print(f"User {member.display_name} left non-AFK for AFK. Processing time spent.")
                 elapsed_time = time.time() - self.voice_timers[user_id]
                 print(f"Elapsed time before AFK for {member.display_name}: {elapsed_time:.2f}s")
                 del self.voice_timers[user_id]
                 print(f"Timer removed for {member.display_name}.")

                 intervals_completed = int(elapsed_time / self.reward_interval)
                 if intervals_completed > 0:
                      reward_amount = intervals_completed * self.voice_reward_amount
                      self.update_balance(user_id, reward_amount)
                      print(f"Rewarded {reward_amount} coins to {member.display_name} for voice activity before AFK.")

            # If switching between two non-AFK channels, timer continues, no action needed here.
            # If switching between two AFK channels, no timer, no action needed.


    @tasks.loop(seconds=60)
    async def reward_users(self):
        # Process message rewards
        if self.message_counts:
            print(f"Processing message rewards for {len(self.message_counts)} users...")
        for user_id, count in list(self.message_counts.items()):
            if count > 0:
                reward_amount = count * self.message_reward_amount
                self.update_balance(user_id, reward_amount)
                # print(f"Rewarded {reward_amount} coins to {user_id} for messages.") # Optional: make this debug print
        self.message_counts.clear()
        if self.message_counts:
            print("Message counts cleared.")

        # Note: Voice rewards are handled on voice state update (on user leaving a channel)
        # If you wanted rewards for *staying* in voice, you'd need a different timer/tracking approach here.


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
            # Use AdminGiveView as defined below (assuming it's outside the Cog or defined later)
            # If AdminGiveView is defined inside the Cog, access it as Economy.AdminGiveView
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

    # --- START OF REWRITTEN LEADERBOARD COMPONENTS ---

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
                    description_lines.append(f"{rank}. {user.mention}: `{balance}` coins")
                else:
                    description_lines.append(f"{rank}. Unknown User (ID: {user_id}): `{balance}` coins")

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


    @nextcord.slash_command(name="leaderboard", description="Display the leaderboard of user balances")
    async def leaderboard_command(self, interaction: nextcord.Interaction):
        """Displays the economy leaderboard with pagination."""
        print(f"'/leaderboard' command triggered by {interaction.user.display_name}")
        try:
            # Defer the initial response immediately
            await interaction.response.defer()
            print("Leaderboard interaction deferred.")

            # Get all balances from the database (efficient)
            # This returns a list of (user_id, balance) tuples, already sorted
            all_user_balances = self.get_all_balances()
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


    # --- END OF REWRITTEN LEADERBOARD COMPONENTS ---


# Keep AdminGiveView outside the Cog class definition if it's a standalone view,
# or ensure it's correctly referenced if defined inside (like Economy.AdminGiveView)
# Assuming AdminGiveView is defined elsewhere or here after the Economy class
class AdminGiveView(nextcord.ui.View):
    def __init__(self, cog, member, amount):
        super().__init__(timeout=60) # Add a timeout
        self.cog = cog
        self.member = member
        self.amount = amount

    @nextcord.ui.button(label="From Balance", style=nextcord.ButtonStyle.green)
    async def from_balance(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer() # Defer interaction
        sender_id = interaction.user.id
        sender_balance = self.cog.get_user_balance(sender_id)
        if sender_balance < self.amount:
            await interaction.followup.send("Insufficient funds.", ephemeral=True)
            self.stop() # Stop the view
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

        await interaction.followup.send(embed=embed) # Use followup after defer
        self.stop()

    @nextcord.ui.button(label="From Treasury", style=nextcord.ButtonStyle.blurple)
    async def from_treasury(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer() # Defer interaction
        self.cog.update_balance(self.member.id, self.amount)
        embed = nextcord.Embed(
            title="Treasury Transaction Successful",
            description=f"{interaction.user.mention} added {self.amount} coins to {self.member.mention} from the treasury.",
            color=nextcord.Color.blue()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
        embed.add_field(name="Recipient", value=self.member.display_name, inline=True)
        embed.add_field(name="Amount", value=f"{self.amount} coins", inline=True)

        await interaction.followup.send(embed=embed) # Use followup after defer
        self.stop()

    async def on_timeout(self):
        # Disable buttons when the view times out
        for item in self.children:
            item.disabled = True
        # For ephemeral views, no need to edit the message as it disappears for the user anyway.
        pass


async def setup(bot):
    bot.add_cog(Economy(bot))
    print("EconomyCog has been added to the bot.")