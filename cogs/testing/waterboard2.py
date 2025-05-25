import nextcord
from nextcord.ext import commands, tasks
import asyncio
import time
import aiosqlite

from server_configs.config import GUILD_ID
from server_configs.cogs_config import seen_category_id, bot_spam_id, admin_user_ids
from cogs.production.economy import Economy

class WaterboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "waterboard.db"
        self.channel_creation_lock = asyncio.Lock()
        self.cooldown_multiplier = 1
        self.waterboard_cost = 200

        self.active_waterboard_sessions = 0
        self.waterboard_sessions_lock = asyncio.Lock() # To protect the counter
        self.temp_channels_being_deleted_flag = False 
        self.temp_channels_deletion_process_lock = asyncio.Lock()

        self._tables_created = False
        
        self.cleanup_exempt_users.start()
        self.reconcile_temp_channels_on_startup.start()

    @staticmethod
    def s_print_static(text_to_print: any) -> str:
        if isinstance(text_to_print, str):
            return text_to_print.encode('ascii', 'replace').decode('ascii')
        return str(text_to_print) # Fallback for non-string types
    
    async def create_tables(self): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS waterboarded_users (
                        user_id INTEGER PRIMARY KEY,
                        last_waterboarded_time REAL,
                        usage_count INTEGER DEFAULT 0,
                        total_waterboarded INTEGER DEFAULT 0,
                        total_coins_spent INTEGER DEFAULT 0
                    )
                ''')
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS temp_channels (
                        channel_id INTEGER PRIMARY KEY
                    )
                ''')
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS exempt_users (
                        user_id INTEGER PRIMARY KEY,
                        exempt_until REAL
                    )
                ''')
                await conn.commit()

    async def get_last_waterboarded_time(self, user_id): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT last_waterboarded_time FROM waterboarded_users WHERE user_id = ?", (user_id,))
                result = await cursor.fetchone()
        return result[0] if result else None

    async def update_last_waterboarded_time(self, user_id, timestamp): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time) VALUES (?, ?)", (user_id, timestamp))
                await conn.commit()

    async def add_temp_channel(self, channel_id): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR IGNORE INTO temp_channels (channel_id) VALUES (?)", (channel_id,))
                await conn.commit()

    async def get_temp_channels(self): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT channel_id FROM temp_channels")
                result = await cursor.fetchall()
        return [row[0] for row in result]

    async def delete_temp_channel(self, channel_id): # Made async
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM temp_channels WHERE channel_id = ?", (channel_id,))
                await conn.commit()

    async def executive_pardon(self, user_to_pardon_id: int, duration_hours: int):
        """Grants an executive pardon to a user, exempting them from waterboarding."""
        exempt_until = time.time() + (duration_hours * 3600)  # Convert hours to seconds
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR REPLACE INTO exempt_users (user_id, exempt_until) VALUES (?, ?)", (user_to_pardon_id, exempt_until))
                await conn.commit()
    async def schedule_temp_channel_deletion_if_needed(self):
        """
        Checks if deletion is warranted and not already in progress, then starts it.
        """
        async with self.temp_channels_deletion_process_lock: # Only one coroutine can assess/start deletion at a time
            if self.temp_channels_being_deleted_flag:
                print("Channel deletion process is already flagged as active or pending. New request ignored.")
                return

            # Final check on session count before committing to deletion
            async with self.waterboard_sessions_lock:
                if self.active_waterboard_sessions > 0:
                    print("Active waterboard sessions resumed before deletion could start. Aborting deletion schedule.")
                    return
                
                # If sessions are still 0, mark that we are proceeding with deletion
                self.temp_channels_being_deleted_flag = True 
        
        # Deletion process starts outside the lock protecting the flag setting
        print("Attempting to delete temporary channels as no sessions are active.")
        try:
            await self._execute_temp_channel_deletion()
        except Exception as e:
            print(f"An error occurred in _execute_temp_channel_deletion: {WaterboardCog.s_print_static(str(e))}")
        finally:
            # Always reset the flag once deletion attempt (successful or not) is complete
            async with self.temp_channels_deletion_process_lock:
                self.temp_channels_being_deleted_flag = False
            print("Temporary channel deletion process finished and flag reset.")

    async def _execute_temp_channel_deletion(self):
        """
        Core logic to delete temporary channels from Discord and database.
        (This is your previous delete_temp_channels method, potentially renamed)
        """
        print("Executing _execute_temp_channel_deletion...")
        # Consider removing or reducing this sleep if faster cleanup is desired
        # and doesn't cause issues with Discord rate limits during rapid succession.
        await asyncio.sleep(1) # From your original file [1]
        
        temp_channel_ids = await self.get_temp_channels() # [1]
        if not temp_channel_ids:
            print("_execute_temp_channel_deletion: No temporary channels found in DB to delete.")
            return

        print(f"_execute_temp_channel_deletion: Found {len(temp_channel_ids)} channels in DB to process for deletion.")
        for channel_id in list(temp_channel_ids): # Iterate over a copy [1]
            channel = self.bot.get_channel(channel_id) # [1]
            discord_channel_deleted = False
            if channel:
                try:
                    channel_name_safe = WaterboardCog.s_print_static(channel.name)
                    print(f"Attempting to delete Discord channel: {channel_name_safe} ({channel_id})")
                    await channel.delete(reason="Waterboard cleanup - no active sessions") # [1]
                    discord_channel_deleted = True
                except nextcord.errors.NotFound:
                    print(f"Discord channel {channel_id} (from DB) not found on Discord (already deleted).")
                    discord_channel_deleted = True # Consider it "deleted" for DB cleanup purposes
                except Exception as e:
                    error_message_safe = str(e).encode('ascii', 'replace').decode('ascii') # [1]
                    print(f"Error deleting Discord channel {channel_id}: {error_message_safe}")
            else:
                print(f"Discord channel for ID {channel_id} (from DB) not found by bot.get_channel (possibly already deleted).")
                discord_channel_deleted = True # If not on Discord, it's effectively "deleted"

            # Remove from DB if the Discord channel is gone or was never found by bot.get_channel
            if discord_channel_deleted:
                try:
                    await self.delete_temp_channel(channel_id) # This is your DB removal method [1]
                    print(f"Removed channel ID {channel_id} from temp_channels DB table.")
                except Exception as e:
                    error_message_safe = str(e).encode('ascii', 'replace').decode('ascii')
                    print(f"Error removing channel ID {channel_id} from DB: {error_message_safe}")
        print("_execute_temp_channel_deletion process completed.")


    @tasks.loop(count=1) # Runs once
    async def reconcile_temp_channels_on_startup(self):
        await self.bot.wait_until_ready()
        print("Reconciling temporary waterboard channels on startup...")
        
        db_channel_ids = await self.get_temp_channels()
        if not db_channel_ids:
            print("No temporary channels in DB to reconcile.")
            return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print(f"Guild {GUILD_ID} not found for reconciliation. Cannot verify/create channels.")
            # Clean up DB entries for which we can't verify channels
            for channel_id in db_channel_ids:
                 await self.delete_temp_channel(channel_id)
            print("Removed all channel IDs from DB as guild was not found.")
            return
            
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        # If seen_category is not found, we can't create new channels,
        # but we can still clean up DB entries for non-existent channels.

        for channel_id in list(db_channel_ids):  # Iterate over a copy
            channel = self.bot.get_channel(channel_id) # More reliable than guild.get_channel for any channel
            if channel and isinstance(channel, nextcord.VoiceChannel):
                if seen_category and channel.category_id != seen_category_id:
                    print(f"Temp channel {channel.name} ({channel_id}) in wrong category. Deleting from Discord & DB.")
                    try:
                        await channel.delete(reason="Reconciliation: Incorrect category")
                    except nextcord.errors.NotFound:
                        pass # Already gone
                    except Exception as e:
                        print(f"Error deleting out-of-category channel {channel_id} during startup: {e}")
                    await self.delete_temp_channel(channel_id)
                # else: Channel exists and is in the correct category (or category not verifiable but channel exists)
                # print(f"Found valid temp channel: {channel.name} ({channel_id})")
            else:
                print(f"Temp channel ID {channel_id} from DB not found on Discord. Removing from DB.")
                await self.delete_temp_channel(channel_id)
        
        # Optional: If after reconciliation, no channels are tracked in DB AND category exists, create them.
        # This ensures channels are ready from the start.
        # current_tracked_channels = await self.get_temp_channels()
        # if not current_tracked_channels and seen_category:
        # print("No temporary channels exist after reconciliation. Creating them now.")
        # await self.create_temp_channels(guild, seen_category)
        # else:
        # print(f"Startup channel reconciliation complete. {len(current_tracked_channels)} channels are tracked.")
        print("Startup channel reconciliation complete.")


    @reconcile_temp_channels_on_startup.before_loop
    async def before_reconcile_temp_channels_on_startup(self):
        await self.bot.wait_until_ready() # [1]
        if not self._tables_created:  # Check the initialized flag
            await self.create_tables() # [1]
            self._tables_created = True # Set flag after creation

    @nextcord.slash_command(name="executivepardon", description="[Admin] Grant exemption from waterboarding for a set time.",guild_ids=[GUILD_ID])
    async def executivepardon_slash_command(self, 
                              interaction: nextcord.Interaction, 
                              user: nextcord.Member, 
                              duration: int = nextcord.SlashOption(name="hours", 
                                                                   description="Duration in hours", 
                                                                   default=1, 
                                                                   required=True)):
        if not hasattr(self, 'bot') or self.bot is None: # Ensure bot is available for create_tables task
            await interaction.response.send_message("Bot is not ready, please try again shortly.", ephemeral=True)
            return
        if interaction.user.id not in admin_user_ids:
            embed = nextcord.Embed(
                title="Permission Denied",
                description="You do not have permission to use this command.",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Call the new core logic function
        await self.executive_pardon(user.id, duration)

        embed = nextcord.Embed(
            title="Executive Pardon",
            description=f"{user.mention} has been pardoned for {duration} hours.",
            color=nextcord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tasks.loop(minutes=10)
    async def cleanup_exempt_users(self):
        await self.bot.wait_until_ready() # Ensures bot is ready before first run
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                current_time = time.time()
                await cursor.execute("DELETE FROM exempt_users WHERE exempt_until < ?", (current_time,))
                await conn.commit()

    @cleanup_exempt_users.before_loop
    async def before_cleanup_exempt_users(self):
        await self.bot.wait_until_ready() # [1]
        if not self._tables_created: # Check the initialized flag
            await self.create_tables() # [1]
            self._tables_created = True # Set flag after creation
    

    @nextcord.slash_command(name="waterboard", description="Waterboard a user",guild_ids=[GUILD_ID])
    async def waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member):
        print(f"User id: {interaction.user.id} used the waterboard command on {user.name}.")
        
        cost = 0
        usage_count_for_next_cost_message = 0


        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                # Check if the user is exempt
                await cursor.execute("SELECT exempt_until FROM exempt_users WHERE user_id = ?", (user.id,))
                exempt_result = await cursor.fetchone() # Renamed to avoid conflict
                if exempt_result:
                    exempt_until = exempt_result[0]
                    if time.time() < exempt_until:
                        embed = nextcord.Embed(
                            title="Exempt User",
                            description=f"{user.mention} is exempt from waterboarding until <t:{int(exempt_until)}:F>.",
                            color=nextcord.Color.red()
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                current_time = time.time()
                await cursor.execute("SELECT last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent FROM waterboarded_users WHERE user_id = ?", (user.id,))
                wb_stats_result = await cursor.fetchone() # Renamed

                current_usage_count = 0 # Usage count for *this* waterboard's cost
                total_waterboarded = 0
                total_coins_spent = 0

                if wb_stats_result:
                    last_waterboarded_time, current_usage_count, total_waterboarded, total_coins_spent = wb_stats_result
                    if current_time - last_waterboarded_time > 1800:  # 30 minutes in seconds
                        current_usage_count = 0
                # else: variables remain at their initial 0 values

                cost = self.waterboard_cost * (self.cooldown_multiplier ** current_usage_count)

                economy_cog = self.bot.get_cog('Economy')
                if not economy_cog:
                    embed_err_econ = nextcord.Embed(title="Error", description="Economy cog is not available.", color=nextcord.Color.red())
                    await interaction.response.send_message(embed=embed_err_econ, ephemeral=True)
                    return

                balance = await economy_cog.get_user_balance(interaction.user.id)
                if balance < cost:
                    embed_insufficient_funds = nextcord.Embed(
                        title="Insufficient Funds",
                        description=f"You need {cost} coins to waterboard {user.mention}. Your current balance is {balance} coins.",
                        color=nextcord.Color.orange()
                    )
                    await interaction.response.send_message(embed=embed_insufficient_funds, ephemeral=True)
                    return

                await economy_cog.deduct_user_balance(interaction.user.id, cost)
                
                # Update stats for the database
                new_db_usage_count = current_usage_count + 1
                usage_count_for_next_cost_message = new_db_usage_count # For the purchase message

                total_waterboarded += 1
                total_coins_spent += cost
                await cursor.execute(
                    "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
                    (user.id, current_time, new_db_usage_count, total_waterboarded, total_coins_spent)
                )
                await conn.commit()

        # Notify the user of the successful purchase
        # This is the first response to the interaction.
        embed_purchased = nextcord.Embed(
            title="Waterboard Purchased",
            description=f"You have successfully waterboarded {user.mention} for {cost} coins. The next usage will cost {self.waterboard_cost * (self.cooldown_multiplier ** usage_count_for_next_cost_message)} coins.",
            color=nextcord.Color.green()
        )
        await interaction.response.send_message(embed=embed_purchased, ephemeral=True)

        # --- NEW: Check if the target user is in a voice channel BEFORE starting the action ---
        if not user.voice or not user.voice.channel:
            print(f"Target user {user.name} is not in a voice channel. Waterboarding action will not proceed.")
            embed_not_in_vc = nextcord.Embed(
                title="Waterboard Action Cancelled",
                description=f"{user.mention} is not in a voice channel. The waterboarding process cannot proceed (you were still charged as the command was initiated).",
                color=nextcord.Color.orange()
            )
            # Use followup.send() because interaction.response.send_message() has already been used.
            await interaction.followup.send(embed=embed_not_in_vc, ephemeral=True)
            return # Stop further processing

        # Proceed with the waterboarding process
        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            embed_no_category = nextcord.Embed(title="Configuration Error", description="The 'seen' category for waterboarding channels was not found. Please contact an admin.", color=nextcord.Color.red())
            await interaction.followup.send(embed=embed_no_category, ephemeral=True) # Also a followup
            return
        

        asyncio.create_task(self.waterboard_user(interaction, user, seen_category))

    @nextcord.slash_command(name="waterboard-ranks", description="All time waterboard rankings.",guild_ids=[GUILD_ID])
    async def leaderboard(self, interaction: nextcord.Interaction):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                # Fetch the top 10 users with the most waterboards
                await cursor.execute("SELECT user_id, total_waterboarded, total_coins_spent FROM waterboarded_users ORDER BY total_waterboarded DESC LIMIT 10")
                results = await cursor.fetchall()

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
            temp_channel_ids = await self.get_temp_channels()
            if not temp_channel_ids:
                water_names = [
                    "💧🌊💧🌊", "🌊🐟🌊💧", "💧💧💧🏞️", "💧🐟💧🐟", "💧💧🐟💧",
                    "🐟💧💧🌊", "💧💧💧💧", "💧🏝️💧💧", "🌊💧💧💧", "💧💧🐟🌊"
                ]
                for name in water_names:
                    channel = await guild.create_voice_channel(name, category=seen_category)
                    await self.add_temp_channel(channel.id)


    async def delete_temp_channels(self):
        # The asyncio.sleep(1) was in your original file.
        # If rapid cleanup is needed and it's not causing issues, it can be kept or adjusted.
        await asyncio.sleep(1) 
        
        temp_channel_ids = await self.get_temp_channels() #
        if not temp_channel_ids:
            print("delete_temp_channels: No temporary channels found in DB to delete.")
            return

        print(f"delete_temp_channels: Attempting to delete {len(temp_channel_ids)} discord channels and their DB entries.")
        for channel_id in list(temp_channel_ids): # Iterate over a copy
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    channel_name_safe = channel.name.encode('ascii', 'replace').decode('ascii')
                    print(f"Deleting Discord channel: {channel_name_safe} ({channel_id})")
                    await channel.delete(reason="Waterboard cleanup")
                except nextcord.errors.NotFound:
                    print(f"Discord channel {channel_id} not found (already deleted).")
                except Exception as e:
                    error_message_safe = str(e).encode('ascii', 'replace').decode('ascii')
                    print(f"Error deleting Discord channel {channel_id}: {error_message_safe}")
            else:
                print(f"Discord channel for ID {channel_id} (from DB) not found by bot.get_channel.")
            
            # Always attempt to remove from DB
            try:
                await self.delete_temp_channel(channel_id) #
                print(f"Removed channel ID {channel_id} from temp_channels DB table.")
            except Exception as e:
                error_message_safe = str(e).encode('ascii', 'replace').decode('ascii')
                print(f"Error removing channel ID {channel_id} from DB: {error_message_safe}")


    async def waterboard_user(self, interaction: nextcord.Interaction, user: nextcord.Member, seen_category): # [1]
        guild = interaction.guild # [1]
        bot_spam_channel = interaction.guild.get_channel(bot_spam_id) # [1]
        original_channel_id = user.voice.channel.id if user.voice else None # [1]

        session_counted = False
        try:
            # --- Increment active session counter ---
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True
            print(f"Waterboard session started for {WaterboardCog.s_print_static(user.name)}. Active sessions: {self.active_waterboard_sessions}")

            # Ensure temporary channels are created if they don't exist.
            await self.create_temp_channels(guild, seen_category) # [1]
            
            temp_channel_ids = await self.get_temp_channels() # [1]

            if not temp_channel_ids: # [1]
                print(f"Error: No temporary channels available for waterboarding {WaterboardCog.s_print_static(user.name)}.")
                # ... (error embed and send logic from your file) ... [1]
                return

            # Voice check is now primarily in the main command, but an extra check here is harmless.
            if not user.voice or user.voice.channel is None: # [1]
                print(f"{WaterboardCog.s_print_static(user.name)} is not in a voice channel (checked in task).")
                # ... (error embed and send logic from your file, if desired here) ... [1]
                return

            # ... (Rest of your user moving logic using WaterboardCog.s_print_static for names) ... [1]

        except Exception as e:
            print(f"Error during waterboarding process for {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}") # [1]
        finally:
            if session_counted:
                should_schedule_deletion = False
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    print(f"Waterboard session ended for {WaterboardCog.s_print_static(user.name)}. Active sessions: {self.active_waterboard_sessions}")
                    if self.active_waterboard_sessions == 0:
                        should_schedule_deletion = True
                
                if should_schedule_deletion:
                    print("All active waterboard sessions concluded. Scheduling check for temp channel deletion.")
                    asyncio.create_task(self.schedule_temp_channel_deletion_if_needed())

            try:
                embed = nextcord.Embed(
                    description=f"{user.mention} was waterboarded by {interaction.user.mention}.",
                    color=nextcord.Color.blue()
                )
                if interaction.response.is_done(): 
                    await interaction.followup.send(embed=embed, ephemeral=True) 
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)

                if bot_spam_channel:
                    public_embed = nextcord.Embed(
                        description=f"{user.mention} was waterboarded by {interaction.user.mention}!",
                        color=nextcord.Color.blue()
                    )
                    await bot_spam_channel.send(embed=public_embed)
            except nextcord.errors.NotFound:
                print(f"Error: Interaction not found for follow-up message for {WaterboardCog.s_print_static(user.name)}.")
            except Exception as e:
                 print(f"Error sending followup/bot-spam message for {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}")

async def setup(bot):
    cog_instance = WaterboardCog(bot)
    if not cog_instance._tables_created:
        await cog_instance.create_tables()
        cog_instance._tables_created = True
    bot.add_cog(cog_instance)
    print("WaterboardCog has been added to the bot.")