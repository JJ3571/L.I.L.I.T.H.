import nextcord
from nextcord.ext import commands
import aiosqlite
import time

from server_configs.config import GUILD_ID
# Ensure this import is correct and admin_user_ids is populated
from server_configs.cogs_config import admin_user_ids

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

    @nextcord.ui.button(label="Lock", style=nextcord.ButtonStyle.grey, custom_id="persistent_lock_button")
    async def lock_button_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_lock_button(interaction)

    @nextcord.ui.button(label="Unlock", style=nextcord.ButtonStyle.grey, custom_id="persistent_unlock_button")
    async def unlock_button_callback(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cog.handle_unlock_button(interaction)


class Buzzer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "buzzer.db"

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
