import nextcord
from nextcord.ext import commands
import aiosqlite
import time

from main_bot.server_configs.config import GUILD_ID
# Ensure this import is correct and admin_user_ids is populated
from main_bot.server_configs.config import admin_user_ids
from main_bot.server_configs.database_config import DATABASE_PATHS

class BuzzerView(nextcord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance

    @nextcord.ui.button(label="BUZZ", style=nextcord.ButtonStyle.green, custom_id="persistent_buzz_button")
    async def buzz_button_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_buzz(interaction)

    @nextcord.ui.button(label="Reset", style=nextcord.ButtonStyle.red, custom_id="persistent_reset_button")
    async def reset_button_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_reset(interaction)

    @nextcord.ui.button(label="Lock", style=nextcord.ButtonStyle.red, custom_id="persistent_lock_button")
    async def lock_button_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_lock_button(interaction)

    @nextcord.ui.button(label="Unlock", style=nextcord.ButtonStyle.grey, custom_id="persistent_unlock_button")
    async def unlock_button_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_unlock_button(interaction)


class VoteView(nextcord.ui.View):
    def __init__(self, cog_instance, message_id: int, num_options: int = 2 ):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.message_id = message_id
        self.num_options = max(1, int(num_options))

        # Create option buttons (grey/secondary)
        for i in range(1, self.num_options + 1):
            opt_idx = i
            btn = nextcord.ui.Button(label=str(opt_idx), style=nextcord.ButtonStyle.secondary, custom_id=f"persistent_vote_{message_id}_{opt_idx}")

            def make_callback(index):
                async def callback(interaction: nextcord.Interaction):
                    await self.cog.handle_vote_select(interaction, index)
                return callback

            # attach a callback bound to the option index
            btn.callback = make_callback(opt_idx)
            self.add_item(btn)

        # Always visible reset button (red)
        reset_btn = nextcord.ui.Button(label="Reset", style=nextcord.ButtonStyle.danger, custom_id=f"persistent_vote_reset_{message_id}")

        async def reset_callback(interaction: nextcord.Interaction):
            await self.cog.handle_vote_reset(interaction)

        reset_btn.callback = reset_callback
        self.add_item(reset_btn)

        # Lock/Unlock button (grey)
        lock_btn = nextcord.ui.Button(label="Lock", style=nextcord.ButtonStyle.red, custom_id=f"persistent_vote_lock_{message_id}")

        async def lock_callback(interaction: nextcord.Interaction):
            await self.cog.handle_vote_lock(interaction)

        lock_btn.callback = lock_callback
        self.add_item(lock_btn)


class Buzzer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["buzzer"]

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS buzzer_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    buzz_time REAL NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS buzzer_sessions (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    locked BOOLEAN NOT NULL DEFAULT FALSE,
                    first_buzz_timestamp REAL DEFAULT NULL
                )
            ''')
            # Vote tables: store sessions (number of options) and individual votes
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vote_sessions (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    num_options INTEGER NOT NULL,
                    locked BOOLEAN NOT NULL DEFAULT FALSE
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    option_index INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    vote_time REAL NOT NULL
                )
            ''')
            await db.commit()
        print("Buzzer database tables created/verified successfully.")


    async def get_session_info(self, message_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT locked, first_buzz_timestamp FROM buzzer_sessions WHERE message_id = ?", (message_id,)) as cursor:
                return await cursor.fetchone()

    async def get_buzz_entries(self, message_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id, username, buzz_time FROM buzzer_entries WHERE message_id = ? ORDER BY buzz_time ASC", (message_id,)) as cursor:
                return await cursor.fetchall()

    async def update_buzzer_embed(self, interaction: nextcord.Interaction = None, message_to_update: nextcord.Message = None):
        if interaction:
            if interaction.message is None:
                print("Error: interaction.message is None in update_buzzer_embed from interaction.")
                # Attempt to send an ephemeral message if interaction is available but message is not.
                try:
                    await interaction.response.send_message("Error: Could not find the original message to update.", ephemeral=True)
                except nextcord.errors.InteractionResponded:
                    await interaction.followup.send("Error: Could not find the original message to update.", ephemeral=True)
                except Exception as e_followup:
                    print(f"Error sending followup for missing message in update_buzzer_embed: {e_followup}")
                return
            message_id = interaction.message.id
            target_message = interaction.message
        elif message_to_update:
            message_id = message_to_update.id
            target_message = message_to_update
        else:
            print("Error: Neither interaction nor message_to_update provided to update_buzzer_embed.")
            return

        if not target_message:
            print(f"Error: Target message could not be determined for message ID {message_id}.")
            return

        session_info = await self.get_session_info(message_id)
        if not session_info:
            embed = nextcord.Embed(title="Buzzer Expired/Cleared", description="This buzzer session is no longer active or the database entry is missing.", color=nextcord.Color.orange())
            try:
                await target_message.edit(embed=embed, view=None) # Clear buttons
            except nextcord.NotFound:
                print(f"Message {message_id} not found when trying to show as expired.")
            except Exception as e:
                print(f"Error editing message to show buzzer expired: {e}")
            return

        locked, first_buzz_db_time = session_info
        buzz_entries = await self.get_buzz_entries(message_id)

        embed_color = nextcord.Color.gold()
        embed_title = "⚡ Buzzer Ready! ⚡"
        if locked:
            embed_title = "🔒 Buzzer Locked 🔒"
            embed_color = nextcord.Color.dark_grey()

        embed = nextcord.Embed(title=embed_title, color=embed_color)

        if not buzz_entries:
            embed.description = "No one has buzzed in yet."
            if locked:
                embed.description = "The buzzer is currently locked by an admin."
        else:
            description_lines = []
            actual_first_buzz_time = buzz_entries[0][2]

            for i, (user_id, username, buzz_time) in enumerate(buzz_entries):
                user = self.bot.get_user(user_id) # Consider fetching member for guild-specific display name if preferred
                display_name = user.mention if user else username

                if i == 0:
                    description_lines.append(f"🥇 **{display_name}** buzzed in first!")
                else:
                    time_diff = buzz_time - actual_first_buzz_time
                    description_lines.append(f"🥈 {display_name} buzzed in `+{time_diff:.2f}s`") # Removed bold for subsequent
            embed.description = "\n".join(description_lines)

        # Always create a new view instance to ensure it's fresh
        current_view = BuzzerView(self)
        try:
            await target_message.edit(embed=embed, view=current_view)
        except nextcord.NotFound:
            print(f"Failed to update embed for message {message_id}: Message not found.")
        except Exception as e:
            print(f"Failed to update embed for message {message_id}: {e}")

    @nextcord.slash_command(name="buzzer", description="Starts a new buzzer session with buttons.", guild_ids=[GUILD_ID])
    async def buzzer_create_subcommand(self, interaction: nextcord.Interaction):
        embed = nextcord.Embed(title="⚡ Buzzer Ready! ⚡", description="Press BUZZ to buzz in!", color=nextcord.Color.gold())
        view = BuzzerView(self)

        msg: nextcord.Message | None = None
        try:
            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_message() # CORRECTED LINE
            if msg is None:
                print("Error starting buzzer: interaction.original_message() returned None")
                await interaction.followup.send("Error starting buzzer: Could not retrieve the message.", ephemeral=True)
                return

        except Exception as e:
            print(f"Error in buzzer_create_subcommand during send/original_message: {e}")
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(f"Error starting buzzer: {e}", ephemeral=True)
                except Exception as ie:
                    print(f"Failed to send ephemeral error (initial response): {ie}")
            else:
                try:
                    await interaction.followup.send(f"Error starting buzzer: {e}", ephemeral=True)
                except Exception as ie:
                    print(f"Failed to send ephemeral error (followup): {ie}")
            return

        message_id = msg.id
        channel_id = interaction.channel_id

        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Ensure old entries for this message_id are cleared if it's somehow reused (though unlikely with new messages)
                await db.execute("DELETE FROM buzzer_sessions WHERE message_id = ?", (message_id,))
                await db.execute("DELETE FROM buzzer_entries WHERE message_id = ?", (message_id,))
                # Create new session
                await db.execute(
                    "INSERT INTO buzzer_sessions (message_id, channel_id, locked, first_buzz_timestamp) VALUES (?, ?, FALSE, NULL)",
                    (message_id, channel_id)
                )
                await db.commit()
        except Exception as e:
            print(f"Database error in buzzer_create_subcommand: {e}")
            # Do not try to send a followup if the original interaction.original_message() failed,
            # as 'msg' would be None and the session wouldn't be properly initialized.
            # The error message above should have already been sent.
            # If msg exists, then we can try to notify about DB error.
            if msg:
                 await interaction.followup.send("Error setting up buzzer session in database.", ephemeral=True)


    async def handle_buzz(self, interaction: nextcord.Interaction):
        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the buzzer message.", ephemeral=True)
            return
        message_id = interaction.message.id
        user_id = interaction.user.id
        username = str(interaction.user) # Using str(interaction.user) gives "Username#discriminator"

        session_info = await self.get_session_info(message_id)
        if not session_info:
            await interaction.response.send_message("This buzzer session may have expired or been cleared.", ephemeral=True)
            try:
                if interaction.message: # Ensure message exists before trying to edit
                    await interaction.message.edit(view=None) # Clear buttons
            except nextcord.NotFound:
                pass # Message already deleted
            except Exception as e:
                print(f"Error clearing view on expired buzz: {e}")
            return

        locked, first_buzz_db_time = session_info

        if locked:
            await interaction.response.send_message("The buzzer is currently locked!", ephemeral=True)
            return

        current_actual_buzz_time = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM buzzer_entries WHERE message_id = ? AND user_id = ?", (message_id, user_id)) as cursor:
                if await cursor.fetchone():
                    await interaction.response.send_message("You have already buzzed in for this round!", ephemeral=True)
                    return

            await db.execute(
                "INSERT INTO buzzer_entries (message_id, user_id, username, buzz_time) VALUES (?, ?, ?, ?)",
                (message_id, user_id, username, current_actual_buzz_time)
            )

            if first_buzz_db_time is None: # This is the first person to buzz
                await db.execute("UPDATE buzzer_sessions SET first_buzz_timestamp = ? WHERE message_id = ?", (current_actual_buzz_time, message_id))

            await db.commit()

        if not interaction.response.is_done():
            await interaction.response.defer() # Defer to acknowledge interaction before updating embed
        await self.update_buzzer_embed(interaction=interaction)

    async def handle_reset(self, interaction: nextcord.Interaction):
        if not (interaction.user.id in admin_user_ids or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("You don't have permission to reset the buzzer.", ephemeral=True)
            return

        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the buzzer message to reset.", ephemeral=True)
            return
        message_id = interaction.message.id

        async with aiosqlite.connect(self.db_path) as db:
            # Clear entries for this specific buzzer
            await db.execute("DELETE FROM buzzer_entries WHERE message_id = ?", (message_id,))
            # Reset the session: unlock it and clear the first buzz timestamp
            await db.execute("UPDATE buzzer_sessions SET first_buzz_timestamp = NULL, locked = FALSE WHERE message_id = ?", (message_id,))
            await db.commit()

        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.update_buzzer_embed(interaction=interaction)
        # Send a confirmation for the reset action
        # if interaction.response.is_done(): # If deferred
        #     await interaction.followup.send("Buzzer has been reset.", ephemeral=True)


    async def handle_lock_button(self, interaction: nextcord.Interaction):
        if not (interaction.user.id in admin_user_ids or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("You don't have permission to lock the buzzer.", ephemeral=True)
            return

        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the buzzer message.", ephemeral=True)
            return
        message_id = interaction.message.id

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("UPDATE buzzer_sessions SET locked = TRUE WHERE message_id = ?", (message_id,))
            await db.commit()
            if cursor.rowcount == 0:
                await interaction.response.send_message(f"No active buzzer session found for this message to lock.", ephemeral=True)
                return

        # await interaction.response.send_message(f"Buzzer has been locked.", ephemeral=True)
        await self.update_buzzer_embed(interaction=interaction)

    async def handle_unlock_button(self, interaction: nextcord.Interaction):
        if not (interaction.user.id in admin_user_ids or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("You don't have permission to unlock the buzzer.", ephemeral=True)
            return

        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the buzzer message.", ephemeral=True)
            return
        message_id = interaction.message.id

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("UPDATE buzzer_sessions SET locked = FALSE WHERE message_id = ?", (message_id,))
            await db.commit()
            if cursor.rowcount == 0:
                await interaction.response.send_message(f"No active buzzer session found for this message to unlock.", ephemeral=True)
                return

        # await interaction.response.send_message(f"Buzzer has been unlocked.", ephemeral=True)
        await self.update_buzzer_embed(interaction=interaction)


    # ----------------- Vote helpers and handlers -----------------
    async def get_vote_session(self, message_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT num_options, locked FROM vote_sessions WHERE message_id = ?", (message_id,)) as cursor:
                return await cursor.fetchone()

    async def get_votes_for_message(self, message_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT option_index, user_id, username FROM votes WHERE message_id = ? ORDER BY option_index ASC, id ASC", (message_id,)) as cursor:
                return await cursor.fetchall()

    async def update_vote_embed(self, interaction: nextcord.Interaction = None, message_to_update: nextcord.Message = None):
        if interaction:
            if interaction.message is None:
                try:
                    await interaction.response.send_message("Error: Could not find the original message to update.", ephemeral=True)
                except Exception:
                    pass
                return
            message_id = interaction.message.id
            target_message = interaction.message
        elif message_to_update:
            message_id = message_to_update.id
            target_message = message_to_update
        else:
            print("Error: Neither interaction nor message_to_update provided to update_vote_embed.")
            return

        session = await self.get_vote_session(message_id)
        if not session:
            embed = nextcord.Embed(title="Vote Expired/Cleared", description="This vote session is no longer active or the database entry is missing.", color=nextcord.Color.orange())
            try:
                await target_message.edit(embed=embed, view=None)
            except Exception as e:
                print(f"Error editing message to show vote expired: {e}")
            return

        (num_options, locked) = session
        votes = await self.get_votes_for_message(message_id)

        # Build lists of mentions/usernames by option
        option_lists = {i: [] for i in range(1, num_options + 1)}
        for option_index, user_id, username in votes:
            user = self.bot.get_user(user_id)
            display = user.mention if user else username
            option_lists.setdefault(option_index, []).append(display)

        embed_title = "Vote"
        if locked:
            embed_title = "Voting Paused"
        embed = nextcord.Embed(title=embed_title, color=nextcord.Color.blurple())
        description_lines = []
        for i in range(1, num_options + 1):
            voters = option_lists.get(i, [])
            if voters:
                # show mentions under the option
                voters_text = ", ".join(voters)
                description_lines.append(f"**{i}: ** {len(voters)} vote(s) — {voters_text}")
            else:
                description_lines.append(f"**{i}: ** 0 votes")

        embed.description = "\n".join(description_lines)

        # create view fresh (message_id used for custom_ids)
        try:
            view = VoteView(self, message_id, num_options)
            await target_message.edit(embed=embed, view=view)
        except Exception as e:
            print(f"Failed to update vote embed for message {message_id}: {e}")

    @nextcord.slash_command(name="vote", description="Start a vote for X things.", guild_ids=[GUILD_ID])
    async def vote_create_subcommand(
        self,
        interaction: nextcord.Interaction,
        num_options: int = nextcord.SlashOption(
            name="number_of_options",
            description="Number of options to vote for (1-20)",
            required=False,
            default=2
        )
    ):
        # Clamp number of options to 1..20 to avoid UI overload
        try:
            num_options = int(num_options)
        except Exception:
            num_options = 2
        num_options = max(1, min(20, num_options))

        embed = nextcord.Embed(title=f"Vote", description="Click a number to vote for that option.", color=nextcord.Color.blurple())
        # show the options in the embed
        embed.description = "\n".join([f"**{i}: **" for i in range(1, num_options + 1)])

        # send initial message first, then attach view that includes message id in custom_ids
        try:
            await interaction.response.send_message(embed=embed)
            msg = await interaction.original_message()
            if msg is None:
                await interaction.followup.send("Error starting vote: Could not retrieve the message.", ephemeral=True)
                return
        except Exception as e:
            print(f"Error in vote_create_subcommand during send/original_message: {e}")
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(f"Error starting vote: {e}", ephemeral=True)
                except Exception:
                    pass
            else:
                try:
                    await interaction.followup.send(f"Error starting vote: {e}", ephemeral=True)
                except Exception:
                    pass
            return

        message_id = msg.id
        channel_id = interaction.channel_id

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM vote_sessions WHERE message_id = ?", (message_id,))
                await db.execute("DELETE FROM votes WHERE message_id = ?", (message_id,))
                await db.execute("INSERT INTO vote_sessions (message_id, channel_id, num_options, locked) VALUES (?, ?, ?, FALSE)", (message_id, channel_id, num_options))
                await db.commit()
        except Exception as e:
            print(f"Database error in vote_create_subcommand: {e}")
            if msg:
                try:
                    await interaction.followup.send("Error setting up vote session in database.", ephemeral=True)
                except Exception:
                    pass

        # attach view with correct custom_ids
        try:
            view = VoteView(self, message_id, num_options)
            await msg.edit(view=view)
        except Exception as e:
            print(f"Failed to attach VoteView to message {message_id}: {e}")

    async def handle_vote_select(self, interaction: nextcord.Interaction, option_index: int):
        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the vote message.", ephemeral=True)
            return
        message_id = interaction.message.id
        user_id = interaction.user.id
        username = str(interaction.user)

        session = await self.get_vote_session(message_id)
        if not session:
            await interaction.response.send_message("This vote session may have expired or been cleared.", ephemeral=True)
            try:
                if interaction.message:
                    await interaction.message.edit(view=None)
            except Exception:
                pass
            return

        (num_options, locked) = session
        
        if locked:
            await interaction.response.send_message("The vote is currently locked!", ephemeral=True)
            return
        
        if option_index < 1 or option_index > num_options:
            await interaction.response.send_message("Invalid option selected.", ephemeral=True)
            return

        async with aiosqlite.connect(self.db_path) as db:
            # Check existing vote
            async with db.execute("SELECT option_index FROM votes WHERE message_id = ? AND user_id = ?", (message_id, user_id)) as cursor:
                row = await cursor.fetchone()

            # If user already voted same option -> remove (toggle off)
            if row and row[0] == option_index:
                await db.execute("DELETE FROM votes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
                await db.commit()

                await self.update_vote_embed(interaction=interaction)
                return

            # otherwise remove any prior vote and insert new
            await db.execute("DELETE FROM votes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
            await db.execute("INSERT INTO votes (message_id, option_index, user_id, username, vote_time) VALUES (?, ?, ?, ?, ?)", (message_id, option_index, user_id, username, time.time()))
            await db.commit()

        # acknowledge and update
        await self.update_vote_embed(interaction=interaction)

    async def handle_vote_lock(self, interaction: nextcord.Interaction):
        # permission check
        if not (interaction.user.id in admin_user_ids or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("You don't have permission to lock the vote.", ephemeral=True)
            return

        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the vote message.", ephemeral=True)
            return
        message_id = interaction.message.id

        session = await self.get_vote_session(message_id)
        if not session:
            await interaction.response.send_message("This vote session may have expired or been cleared.", ephemeral=True)
            return

        (num_options, locked) = session

        # Toggle lock status
        new_locked_status = not locked
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE vote_sessions SET locked = ? WHERE message_id = ?", (new_locked_status, message_id))
            await db.commit()

        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.update_vote_embed(interaction=interaction)

    async def handle_vote_reset(self, interaction: nextcord.Interaction):
        # permission check
        if not (interaction.user.id in admin_user_ids or interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message("You don't have permission to reset votes.", ephemeral=True)
            return

        if interaction.message is None:
            await interaction.response.send_message("Error: Could not identify the vote message.", ephemeral=True)
            return
        message_id = interaction.message.id

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM votes WHERE message_id = ?", (message_id,))
            await db.commit()

        if not interaction.response.is_done():
            await interaction.response.send_message("Votes have been reset.", ephemeral=True)
        await self.update_vote_embed(interaction=interaction)


    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.__class__.__name__} cog is ready.")
        try:
            await self.create_tables()
        except Exception as e:
            print(f"Failed to create tables during on_ready: {e}")

        # View registration logic
        # The flag _buzzer_view_added should be set on the bot instance by the setup function
        # to ensure this view is added only once across bot restarts if the cog is reloaded.
        # However, for persistent views, you register them once with custom_ids,
        # and the bot handles them. The add_view call should happen if the views
        # haven't been registered with the bot's listener yet.
        # A common pattern is to just add it; Nextcord is generally idempotent with add_view.
        # For true persistence across bot restarts (not just cog reloads),
        # the view needs to be added when the bot starts up.
        self.bot.add_view(BuzzerView(self))
        print("Persistent BuzzerView registered/re-affirmed with the bot.")


async def setup(bot):
    cog = Buzzer(bot)
    await cog.create_tables()
    bot.add_cog(cog)
    print("BuzzerCog loaded.")
