import nextcord
from nextcord.ext import commands, tasks
import asyncio
import time
import aiosqlite

from server_configs.config import GUILD_ID
from server_configs.cogs_config import seen_category_id, bot_spam_id, admin_user_ids
from cogs.production.economy import Economy
from server_configs.database_config import DATABASE_PATHS

class WaterboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["waterboard"]
        self.channel_creation_lock = asyncio.Lock()
        self.cooldown_multiplier = 2
        self.waterboard_cost = 200

        self.active_waterboard_sessions = 0
        self.waterboard_sessions_lock = asyncio.Lock() 
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

    async def get_last_waterboarded_time(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT last_waterboarded_time FROM waterboarded_users WHERE user_id = ?", (user_id,))
                result = await cursor.fetchone()
        return result[0] if result else None

    async def update_last_waterboarded_time(self, user_id, timestamp):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time) VALUES (?, ?)", (user_id, timestamp))
                await conn.commit()

    async def add_temp_channel(self, channel_id): 
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT OR IGNORE INTO temp_channels (channel_id) VALUES (?)", (channel_id,))
                await conn.commit()

    async def get_temp_channels(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT channel_id FROM temp_channels")
                result = await cursor.fetchall()
        return [row[0] for row in result]

    async def delete_temp_channel(self, channel_id):
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
        await asyncio.sleep(1)
        
        temp_channel_ids = await self.get_temp_channels()
        if not temp_channel_ids:
            print("_execute_temp_channel_deletion: No temporary channels found in DB to delete.")
            return

        print(f"_execute_temp_channel_deletion: Found {len(temp_channel_ids)} channels in DB to process for deletion.")
        for channel_id in list(temp_channel_ids): 
            channel = self.bot.get_channel(channel_id)
            discord_channel_deleted = False
            if channel:
                try:
                    channel_name_safe = WaterboardCog.s_print_static(channel.name)
                    print(f"Attempting to delete Discord channel: {channel_name_safe} ({channel_id})")
                    await channel.delete(reason="Waterboard cleanup - no active sessions")
                    discord_channel_deleted = True
                except nextcord.errors.NotFound:
                    print(f"Discord channel {channel_id} (from DB) not found on Discord (already deleted).")
                    discord_channel_deleted = True
                except Exception as e:
                    error_message_safe = str(e).encode('ascii', 'replace').decode('ascii')
                    print(f"Error deleting Discord channel {channel_id}: {error_message_safe}")
            else:
                print(f"Discord channel for ID {channel_id} (from DB) not found by bot.get_channel (possibly already deleted).")
                discord_channel_deleted = True # If not on Discord, it's effectively "deleted"

            # Remove from DB if the Discord channel is gone or was never found by bot.get_channel
            if discord_channel_deleted:
                try:
                    await self.delete_temp_channel(channel_id)
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
            for channel_id in db_channel_ids:
                 await self.delete_temp_channel(channel_id)
            print("Removed all channel IDs from DB as guild was not found.")
            return
            
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)

        for channel_id in list(db_channel_ids): 
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
            else:
                print(f"Temp channel ID {channel_id} from DB not found on Discord. Removing from DB.")
                await self.delete_temp_channel(channel_id)
        

        print("Startup channel reconciliation complete.")


    @reconcile_temp_channels_on_startup.before_loop
    async def before_reconcile_temp_channels_on_startup(self):
        await self.bot.wait_until_ready() 
        if not self._tables_created:  # Check the initialized flag
            await self.create_tables()
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
        
        await self.executive_pardon(user.id, duration)

        embed = nextcord.Embed(
            title="Executive Pardon",
            description=f"{user.mention} has been pardoned for {duration} hours.",
            color=nextcord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tasks.loop(minutes=10)
    async def cleanup_exempt_users(self):
        await self.bot.wait_until_ready()
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                current_time = time.time()
                await cursor.execute("DELETE FROM exempt_users WHERE exempt_until < ?", (current_time,))
                await conn.commit()

    @cleanup_exempt_users.before_loop
    async def before_cleanup_exempt_users(self):
        await self.bot.wait_until_ready()
        if not self._tables_created: # Check the initialized flag
            await self.create_tables()
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
                exempt_result = await cursor.fetchone() 
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
                wb_stats_result = await cursor.fetchone() 

                current_usage_count = 0 # Usage count for *this* waterboard's cost
                total_waterboarded = 0
                total_coins_spent = 0

                if wb_stats_result:
                    last_waterboarded_time, current_usage_count, total_waterboarded, total_coins_spent = wb_stats_result
                    if current_time - last_waterboarded_time > 1800:  # 30 minutes in seconds
                        current_usage_count = 0

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
                
                new_db_usage_count = current_usage_count + 1
                usage_count_for_next_cost_message = new_db_usage_count

                total_waterboarded += 1
                total_coins_spent += cost
                await cursor.execute(
                    "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
                    (user.id, current_time, new_db_usage_count, total_waterboarded, total_coins_spent)
                )
                await conn.commit()


        embed_purchased = nextcord.Embed(
            title="Waterboard Purchased",
            description=f"You have successfully waterboarded {user.mention} for {cost} coins. The next usage will cost {self.waterboard_cost * (self.cooldown_multiplier ** usage_count_for_next_cost_message)} coins.",
            color=nextcord.Color.green()
        )
        await interaction.response.send_message(embed=embed_purchased, ephemeral=True)

        # Check if the target user is in a voice channel BEFORE starting
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

        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            embed_no_category = nextcord.Embed(title="Configuration Error", description="The 'seen' category for waterboarding channels was not found. Please contact an admin.", color=nextcord.Color.red())
            await interaction.followup.send(embed=embed_no_category, ephemeral=True) 
            return
        

        asyncio.create_task(self.waterboard_user(interaction, user, seen_category))

    @nextcord.slash_command(name="enhanced-waterboard", description="Enhanced waterboard that hides the original voice channel", guild_ids=[GUILD_ID])
    async def enhanced_waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member):
        print(f"User id: {interaction.user.id} used the enhanced-waterboard command on {user.name}.")
        
        cost = 0
        usage_count_for_next_cost_message = 0

        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                # Check if the user is exempt
                await cursor.execute("SELECT exempt_until FROM exempt_users WHERE user_id = ?", (user.id,))
                exempt_result = await cursor.fetchone() 
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
                wb_stats_result = await cursor.fetchone() 

                current_usage_count = 0
                total_waterboarded = 0
                total_coins_spent = 0

                if wb_stats_result:
                    last_waterboarded_time, current_usage_count, total_waterboarded, total_coins_spent = wb_stats_result
                    if current_time - last_waterboarded_time > 1800:  # 30 minutes in seconds
                        current_usage_count = 0

                # Enhanced waterboard costs 1.5x the normal cost
                enhanced_cost_multiplier = 1.5
                cost = int(self.waterboard_cost * enhanced_cost_multiplier * (self.cooldown_multiplier ** current_usage_count))

                economy_cog = self.bot.get_cog('Economy')
                if not economy_cog:
                    embed_err_econ = nextcord.Embed(title="Error", description="Economy cog is not available.", color=nextcord.Color.red())
                    await interaction.response.send_message(embed=embed_err_econ, ephemeral=True)
                    return

                balance = await economy_cog.get_user_balance(interaction.user.id)
                if balance < cost:
                    embed_insufficient_funds = nextcord.Embed(
                        title="Insufficient Funds",
                        description=f"You need {cost} coins to enhanced waterboard {user.mention}. Your current balance is {balance} coins.",
                        color=nextcord.Color.orange()
                    )
                    await interaction.response.send_message(embed=embed_insufficient_funds, ephemeral=True)
                    return

                await economy_cog.deduct_user_balance(interaction.user.id, cost)
                
                new_db_usage_count = current_usage_count + 1
                usage_count_for_next_cost_message = new_db_usage_count

                total_waterboarded += 1
                total_coins_spent += cost
                await cursor.execute(
                    "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
                    (user.id, current_time, new_db_usage_count, total_waterboarded, total_coins_spent)
                )
                await conn.commit()

        next_cost = int(self.waterboard_cost * enhanced_cost_multiplier * (self.cooldown_multiplier ** usage_count_for_next_cost_message))
        embed_purchased = nextcord.Embed(
            title="Enhanced Waterboard Purchased",
            description=f"You have successfully enhanced waterboarded {user.mention} for {cost} coins. The next enhanced usage will cost {next_cost} coins.",
            color=nextcord.Color.dark_blue()
        )
        await interaction.response.send_message(embed=embed_purchased, ephemeral=True)

        # Check if the target user is in a voice channel BEFORE starting
        if not user.voice or not user.voice.channel:
            print(f"Target user {user.name} is not in a voice channel. Enhanced waterboarding action will not proceed.")
            embed_not_in_vc = nextcord.Embed(
                title="Enhanced Waterboard Action Cancelled",
                description=f"{user.mention} is not in a voice channel. The enhanced waterboarding process cannot proceed (you were still charged as the command was initiated).",
                color=nextcord.Color.orange()
            )
            await interaction.followup.send(embed=embed_not_in_vc, ephemeral=True)
            return

        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            embed_no_category = nextcord.Embed(title="Configuration Error", description="The 'seen' category for waterboarding channels was not found. Please contact an admin.", color=nextcord.Color.red())
            await interaction.followup.send(embed=embed_no_category, ephemeral=True) 
            return

        asyncio.create_task(self.enhanced_waterboard_user(interaction, user, seen_category))

    @nextcord.slash_command(name="waterboard-party", description="Waterboard everyone in a voice channel (except yourself)", guild_ids=[GUILD_ID])
    async def waterboard_party(self, interaction: nextcord.Interaction):
        print(f"User id: {interaction.user.id} used the waterboard-party command.")
        
        # Check if the user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = nextcord.Embed(
                title="Not in Voice Channel",
                description="You must be in a voice channel to use the waterboard party command.",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        user_voice_channel = interaction.user.voice.channel
        
        # Get all users in the voice channel except the command initiator
        target_users = [member for member in user_voice_channel.members if member.id != interaction.user.id and not member.bot]
        
        if not target_users:
            embed = nextcord.Embed(
                title="No Targets Found",
                description="There are no other users in your voice channel to waterboard.",
                color=nextcord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Calculate total cost (base cost * number of users * party multiplier)
        party_multiplier = 2.5  # Party commands cost more
        base_cost_per_user = self.waterboard_cost
        total_cost = int(base_cost_per_user * party_multiplier * len(target_users))

        # Check economy
        economy_cog = self.bot.get_cog('Economy')
        if not economy_cog:
            embed_err_econ = nextcord.Embed(title="Error", description="Economy cog is not available.", color=nextcord.Color.red())
            await interaction.response.send_message(embed=embed_err_econ, ephemeral=True)
            return

        balance = await economy_cog.get_user_balance(interaction.user.id)
        if balance < total_cost:
            embed_insufficient_funds = nextcord.Embed(
                title="Insufficient Funds",
                description=f"You need {total_cost} coins to waterboard {len(target_users)} users. Your current balance is {balance} coins.",
                color=nextcord.Color.orange()
            )
            await interaction.response.send_message(embed=embed_insufficient_funds, ephemeral=True)
            return

        # Check for exempt users and filter them out
        exempt_users = []
        final_target_users = []
        
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                current_time = time.time()
                for user in target_users:
                    await cursor.execute("SELECT exempt_until FROM exempt_users WHERE user_id = ?", (user.id,))
                    exempt_result = await cursor.fetchone()
                    if exempt_result and current_time < exempt_result[0]:
                        exempt_users.append(user)
                    else:
                        final_target_users.append(user)

        if not final_target_users:
            exempt_list = ", ".join([user.mention for user in exempt_users])
            embed = nextcord.Embed(
                title="All Users Exempt",
                description=f"All users in the channel are exempt from waterboarding: {exempt_list}",
                color=nextcord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Recalculate cost for non-exempt users
        final_cost = int(base_cost_per_user * party_multiplier * len(final_target_users))
        if balance < final_cost:
            embed_insufficient_funds = nextcord.Embed(
                title="Insufficient Funds",
                description=f"You need {final_cost} coins to waterboard {len(final_target_users)} non-exempt users. Your current balance is {balance} coins.",
                color=nextcord.Color.orange()
            )
            await interaction.response.send_message(embed=embed_insufficient_funds, ephemeral=True)
            return

        # Deduct the cost
        await economy_cog.deduct_user_balance(interaction.user.id, final_cost)

        # Update database for each user
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                current_time = time.time()
                for user in final_target_users:
                    await cursor.execute("SELECT total_waterboarded, total_coins_spent FROM waterboarded_users WHERE user_id = ?", (user.id,))
                    result = await cursor.fetchone()
                    if result:
                        total_waterboarded, total_coins_spent = result
                        total_waterboarded += 1
                        total_coins_spent += int(base_cost_per_user * party_multiplier)
                    else:
                        total_waterboarded = 1
                        total_coins_spent = int(base_cost_per_user * party_multiplier)
                    
                    await cursor.execute(
                        "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
                        (user.id, current_time, 0, total_waterboarded, total_coins_spent)
                    )
                await conn.commit()

        # Send confirmation message
        target_mentions = ", ".join([user.mention for user in final_target_users])
        exempt_message = ""
        if exempt_users:
            exempt_mentions = ", ".join([user.mention for user in exempt_users])
            exempt_message = f"\n\nExempt users (not waterboarded): {exempt_mentions}"

        embed_purchased = nextcord.Embed(
            title="Waterboard Party Purchased",
            description=f"You have successfully initiated a waterboard party for {final_cost} coins!\n\nTargets: {target_mentions}{exempt_message}",
            color=nextcord.Color.purple()
        )
        await interaction.response.send_message(embed=embed_purchased, ephemeral=True)

        # Get the seen category
        guild = interaction.guild
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            embed_no_category = nextcord.Embed(title="Configuration Error", description="The 'seen' category for waterboarding channels was not found. Please contact an admin.", color=nextcord.Color.red())
            await interaction.followup.send(embed=embed_no_category, ephemeral=True) 
            return

        # Start the party waterboard process
        asyncio.create_task(self.waterboard_party_users(interaction, final_target_users, seen_category, user_voice_channel))

    async def enhanced_waterboard_user(self, interaction: nextcord.Interaction, user: nextcord.Member, seen_category):
        guild = interaction.guild
        bot_spam_channel = interaction.guild.get_channel(bot_spam_id)
        original_channel = user.voice.channel if user.voice else None
        original_channel_id = original_channel.id if original_channel else None
        
        # Store original permissions for the target user
        original_permissions = None
        if original_channel:
            original_permissions = original_channel.overwrites_for(user)

        session_counted = False
        try:
            # Increment active session counter
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True
            print(f"Enhanced waterboard session started for {WaterboardCog.s_print_static(user.name)}. Active sessions: {self.active_waterboard_sessions}")

            # Hide the original channel from the target user
            if original_channel:
                try:
                    overwrite = nextcord.PermissionOverwrite(view_channel=False)
                    await original_channel.set_permissions(user, overwrite=overwrite, reason="Enhanced waterboard - hiding channel")
                    print(f"Hidden original channel {WaterboardCog.s_print_static(original_channel.name)} from {WaterboardCog.s_print_static(user.name)}")
                except Exception as e:
                    print(f"Error hiding channel from {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}")

            # Ensure temporary channels are created if they don't exist
            await self.create_temp_channels(guild, seen_category) 
            
            temp_channel_ids = await self.get_temp_channels()

            if not temp_channel_ids:
                print(f"Error: No temporary channels available for enhanced waterboarding {WaterboardCog.s_print_static(user.name)}.")
                return

            # Voice check (primarily in main command, safeguard here)
            if not user.voice or user.voice.channel is None:
                print(f"{WaterboardCog.s_print_static(user.name)} is not in a voice channel (checked in enhanced task).")
                return

            print(f"Starting enhanced channel movement for {WaterboardCog.s_print_static(user.name)}.")
            # Move user through the temporary channels (same as regular waterboard)
            for channel_id in temp_channel_ids:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    print(f"Temporary channel {channel_id} not found during enhanced waterboarding of {WaterboardCog.s_print_static(user.name)}.")
                    continue 
                
                # For enhanced waterboard, if user disconnects, we move them back to original channel first
                if not user.voice or user.voice.channel is None:
                    print(f"{WaterboardCog.s_print_static(user.name)} disconnected during enhanced waterboarding. Attempting to move back to original channel.")
                    if original_channel:
                        try:
                            # Temporarily allow them to see the channel to move them back
                            temp_overwrite = nextcord.PermissionOverwrite(view_channel=True, connect=True)
                            await original_channel.set_permissions(user, overwrite=temp_overwrite, reason="Enhanced waterboard - temporary access for return")
                            await user.move_to(original_channel)
                            print(f"Moved {WaterboardCog.s_print_static(user.name)} back to original channel after disconnect.")
                            # Hide the channel again
                            overwrite = nextcord.PermissionOverwrite(view_channel=False)
                            await original_channel.set_permissions(user, overwrite=overwrite, reason="Enhanced waterboard - re-hiding channel")
                        except Exception as e:
                            print(f"Error moving {WaterboardCog.s_print_static(user.name)} back after disconnect: {WaterboardCog.s_print_static(str(e))}")
                            break
                    else:
                        break
                
                print(f"Moving {WaterboardCog.s_print_static(user.name)} to temporary channel: {WaterboardCog.s_print_static(channel.name)}.")
                try:
                    await user.move_to(channel)
                except nextcord.errors.HTTPException as e:
                    print(f"Failed to move {WaterboardCog.s_print_static(user.name)} to {WaterboardCog.s_print_static(channel.name)}: {WaterboardCog.s_print_static(str(e))}")
                    if e.status == 400:
                        print(f"User {WaterboardCog.s_print_static(user.name)} likely disconnected or channel issue during enhanced waterboard.")
                        # Try to move them back to original channel
                        if original_channel:
                            try:
                                temp_overwrite = nextcord.PermissionOverwrite(view_channel=True, connect=True)
                                await original_channel.set_permissions(user, overwrite=temp_overwrite, reason="Enhanced waterboard - temporary access for return")
                                await user.move_to(original_channel)
                                print(f"Moved {WaterboardCog.s_print_static(user.name)} back to original channel after error.")
                            except Exception as move_error:
                                print(f"Error moving {WaterboardCog.s_print_static(user.name)} back after error: {WaterboardCog.s_print_static(str(move_error))}")
                        break 
                await asyncio.sleep(1.3)

            # Move the user back to the original channel
            if original_channel:
                print(f"Moving {WaterboardCog.s_print_static(user.name)} back to the original channel after enhanced waterboard.")
                try:
                    # Temporarily allow them to see and connect to the channel
                    temp_overwrite = nextcord.PermissionOverwrite(view_channel=True, connect=True)
                    await original_channel.set_permissions(user, overwrite=temp_overwrite, reason="Enhanced waterboard - temporary access for return")
                    
                    # Move them back
                    await user.move_to(original_channel)
                    print(f"{WaterboardCog.s_print_static(user.name)} has been moved back to the original channel after enhanced waterboard.")
                except Exception as e:
                    print(f"Error moving {WaterboardCog.s_print_static(user.name)} back to original channel: {WaterboardCog.s_print_static(str(e))}")
            else:
                print(f"Original channel not found for {WaterboardCog.s_print_static(user.name)} in enhanced waterboard.")

        except Exception as e:
            print(f"Error during enhanced waterboarding process for {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}")
        finally:
            # Always restore original permissions
            if original_channel:
                try:
                    if original_permissions:
                        await original_channel.set_permissions(user, overwrite=original_permissions, reason="Enhanced waterboard - restoring original permissions")
                    else:
                        await original_channel.set_permissions(user, overwrite=None, reason="Enhanced waterboard - removing custom permissions")
                    print(f"Restored original permissions for {WaterboardCog.s_print_static(user.name)} in {WaterboardCog.s_print_static(original_channel.name)}")
                except Exception as e:
                    print(f"Error restoring permissions for {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}")

            if session_counted:
                should_schedule_deletion = False
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    print(f"Enhanced waterboard session ended for {WaterboardCog.s_print_static(user.name)}. Active sessions: {self.active_waterboard_sessions}")
                    if self.active_waterboard_sessions == 0:
                        should_schedule_deletion = True
                
                if should_schedule_deletion:
                    print("All active waterboard sessions concluded. Scheduling check for temp channel deletion.")
                    asyncio.create_task(self.schedule_temp_channel_deletion_if_needed())

            # Final message sending logic
            try:
                embed = nextcord.Embed(
                    description=f"{user.mention} was enhanced waterboarded by {interaction.user.mention}.",
                    color=nextcord.Color.dark_blue()
                )
                if interaction.response.is_done(): 
                    await interaction.followup.send(embed=embed, ephemeral=True) 
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)

                if bot_spam_channel:
                    public_embed = nextcord.Embed(
                        description=f"{user.mention} was enhanced waterboarded by {interaction.user.mention}! 💀",
                        color=nextcord.Color.dark_blue()
                    )
                    await bot_spam_channel.send(embed=public_embed)
            except nextcord.errors.NotFound:
                print(f"Error: Interaction not found for follow-up message for enhanced waterboard of {WaterboardCog.s_print_static(user.name)}.")
            except Exception as e:
                print(f"Error sending followup/bot-spam message for enhanced waterboard of {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}")

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
                    "🐟💧💧🌊", "💧💧💧💧", "💧🏝️💧💧", 
                    # "🌊💧💧💧", "💧💧🐟🌊"
                    # Commented out to reduce channel count. Rate limiting :D
                ]
                for name in water_names:
                    channel = await guild.create_voice_channel(name, category=seen_category)
                    await self.add_temp_channel(channel.id)


    async def delete_temp_channels(self):
        await asyncio.sleep(1) 
        
        temp_channel_ids = await self.get_temp_channels()
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
                await self.delete_temp_channel(channel_id)
                print(f"Removed channel ID {channel_id} from temp_channels DB table.")
            except Exception as e:
                error_message_safe = str(e).encode('ascii', 'replace').decode('ascii')
                print(f"Error removing channel ID {channel_id} from DB: {error_message_safe}")

    async def waterboard_user(self, interaction: nextcord.Interaction, user: nextcord.Member, seen_category):
        guild = interaction.guild
        bot_spam_channel = interaction.guild.get_channel(bot_spam_id)
        original_channel_id = user.voice.channel.id if user.voice else None

        session_counted = False
        try:
            # Increment active session counter
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True
            print(f"Waterboard session started for {WaterboardCog.s_print_static(user.name)}. Active sessions: {self.active_waterboard_sessions}")

            # Ensure temporary channels are created if they don't exist.
            await self.create_temp_channels(guild, seen_category) 
            
            temp_channel_ids = await self.get_temp_channels()

            if not temp_channel_ids:
                print(f"Error: No temporary channels available for waterboarding {WaterboardCog.s_print_static(user.name)}.")
                return

            # Voice check (primarily in main command, safeguard here)
            if not user.voice or user.voice.channel is None:
                print(f"{WaterboardCog.s_print_static(user.name)} is not in a voice channel (checked in task).")
                return

            print(f"Starting channel movement for {WaterboardCog.s_print_static(user.name)}.")
            # Move user through the temporary channels
            for channel_id in temp_channel_ids:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    print(f"Temporary channel {channel_id} not found during waterboarding of {WaterboardCog.s_print_static(user.name)}.") #
                    continue 
                if not user.voice or user.voice.channel is None: # Check if user disconnected mid-process
                    print(f"{WaterboardCog.s_print_static(user.name)} disconnected or moved out of voice channel during waterboarding.") #
                    break 
                print(f"Moving {WaterboardCog.s_print_static(user.name)} to temporary channel: {WaterboardCog.s_print_static(channel.name)}.") #
                try:
                    await user.move_to(channel)
                except nextcord.errors.HTTPException as e:
                    print(f"Failed to move {WaterboardCog.s_print_static(user.name)} to {WaterboardCog.s_print_static(channel.name)}: {WaterboardCog.s_print_static(str(e))}") #
                    if e.status == 400: # e.g., user disconnected, channel full/deleted
                        print(f"User {WaterboardCog.s_print_static(user.name)} likely disconnected or channel issue. Aborting moves for this user.") #
                        break 
                await asyncio.sleep(1.3) # Delay to simulate the waterboarding process

            # Move the user back to the original channel
            if user.voice and original_channel_id: # # Check if user is still in a voice channel
                print(f"Moving {WaterboardCog.s_print_static(user.name)} back to the original channel.")
                original_channel = self.bot.get_channel(original_channel_id)
                if original_channel:
                    try:
                        await user.move_to(original_channel) #
                        print(f"{WaterboardCog.s_print_static(user.name)} has been moved back to the original channel.") #
                    except Exception as e: #
                        print(f"Error moving {WaterboardCog.s_print_static(user.name)} back to original channel: {WaterboardCog.s_print_static(str(e))}") #
                else:
                    print(f"Original channel not found for {WaterboardCog.s_print_static(user.name)}.") #
            else:
                print(f"{WaterboardCog.s_print_static(user.name)} is not in a voice channel or original channel is not available to move back.") #
            # --- END OF RE-INSERTED USER MOVEMENT LOGIC ---

        except Exception as e: #
            print(f"Error during waterboarding process for {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}") #
        finally: #
            if session_counted: #
                should_schedule_deletion = False #
                async with self.waterboard_sessions_lock: #
                    self.active_waterboard_sessions -= 1 #
                    print(f"Waterboard session ended for {WaterboardCog.s_print_static(user.name)}. Active sessions: {self.active_waterboard_sessions}") #
                    if self.active_waterboard_sessions == 0: #
                        should_schedule_deletion = True #
                
                if should_schedule_deletion: #
                    print("All active waterboard sessions concluded. Scheduling check for temp channel deletion.") #
                    asyncio.create_task(self.schedule_temp_channel_deletion_if_needed()) #

            # Final message sending logic
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
                print(f"Error: Interaction not found for follow-up message for {WaterboardCog.s_print_static(user.name)}.") #
            except Exception as e:
                 print(f"Error sending followup/bot-spam message for {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}") #

    async def waterboard_party_users(self, interaction: nextcord.Interaction, target_users: list, seen_category, original_channel):
        """
        Waterboards multiple users simultaneously through 5 water channels.
        """
        guild = interaction.guild
        bot_spam_channel = interaction.guild.get_channel(bot_spam_id)
        original_channel_id = original_channel.id

        session_counted = False
        active_users = list(target_users)  # Track users who are still connected
        
        try:
            # Increment active session counter
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True
            
            user_names = [WaterboardCog.s_print_static(user.name) for user in target_users]
            print(f"Waterboard party session started for {len(target_users)} users: {', '.join(user_names)}. Active sessions: {self.active_waterboard_sessions}")

            # Ensure temporary channels are created if they don't exist
            await self.create_temp_channels(guild, seen_category) 
            
            temp_channel_ids = await self.get_temp_channels()

            if not temp_channel_ids:
                print(f"Error: No temporary channels available for waterboard party.")
                return

            # Filter out users who are no longer in voice before starting
            active_users = [user for user in active_users if user.voice and user.voice.channel]
            
            if not active_users:
                print("No users are in voice channels for waterboard party.")
                return

            print(f"Starting waterboard party for {len(active_users)} users through {len(temp_channel_ids)} channels.")
            
            # Move all users through exactly 5 water channels (repeat channels if necessary)
            water_channels_to_use = []
            for i in range(5):  # Exactly 5 channels
                channel_id = temp_channel_ids[i % len(temp_channel_ids)]  # Cycle through available channels
                water_channels_to_use.append(channel_id)

            # Move users through each water channel
            for round_num, channel_id in enumerate(water_channels_to_use, 1):
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    print(f"Temporary channel {channel_id} not found during waterboard party round {round_num}.")
                    continue 

                # Filter out disconnected users before each move
                previously_active = len(active_users)
                active_users = [user for user in active_users if user.voice and user.voice.channel]
                
                if len(active_users) < previously_active:
                    disconnected_count = previously_active - len(active_users)
                    print(f"Round {round_num}: {disconnected_count} user(s) disconnected, continuing with {len(active_users)} remaining users.")
                
                if not active_users:
                    print(f"All users disconnected during waterboard party at round {round_num}.")
                    break

                print(f"Round {round_num}/5: Moving {len(active_users)} users to {WaterboardCog.s_print_static(channel.name)}")
                
                # Move all active users to the current water channel
                for user in list(active_users):  # Use list() to avoid modification during iteration
                    try:
                        await user.move_to(channel)
                        print(f"  Moved {WaterboardCog.s_print_static(user.name)} to {WaterboardCog.s_print_static(channel.name)}")
                    except nextcord.errors.HTTPException as e:
                        print(f"  Failed to move {WaterboardCog.s_print_static(user.name)} to {WaterboardCog.s_print_static(channel.name)}: {WaterboardCog.s_print_static(str(e))}")
                        if e.status == 400:  # User likely disconnected
                            print(f"  User {WaterboardCog.s_print_static(user.name)} likely disconnected. Removing from active list.")
                            if user in active_users:
                                active_users.remove(user)
                    except Exception as e:
                        print(f"  Unexpected error moving {WaterboardCog.s_print_static(user.name)}: {WaterboardCog.s_print_static(str(e))}")
                        if user in active_users:
                            active_users.remove(user)

                # Wait between channel moves
                await asyncio.sleep(1.8)  # Slightly longer delay for party mode

            # Move remaining users back to the original channel
            if active_users:
                print(f"Moving {len(active_users)} remaining users back to original channel.")
                original_channel_obj = self.bot.get_channel(original_channel_id)
                if original_channel_obj:
                    for user in active_users:
                        try:
                            await user.move_to(original_channel_obj)
                            print(f"  Moved {WaterboardCog.s_print_static(user.name)} back to original channel.")
                        except Exception as e:
                            print(f"  Error moving {WaterboardCog.s_print_static(user.name)} back to original channel: {WaterboardCog.s_print_static(str(e))}")
                else:
                    print(f"Original channel not found for waterboard party return.")
            else:
                print("No users remaining to move back to original channel.")

        except Exception as e:
            print(f"Error during waterboard party process: {WaterboardCog.s_print_static(str(e))}")
        finally:
            if session_counted:
                should_schedule_deletion = False
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    print(f"Waterboard party session ended. Active sessions: {self.active_waterboard_sessions}")
                    if self.active_waterboard_sessions == 0:
                        should_schedule_deletion = True
                
                if should_schedule_deletion:
                    print("All active waterboard sessions concluded. Scheduling check for temp channel deletion.")
                    asyncio.create_task(self.schedule_temp_channel_deletion_if_needed())

            # Send completion messages
            try:
                final_active_count = len([user for user in target_users if user.voice and user.voice.channel])
                disconnected_count = len(target_users) - final_active_count
                
                target_mentions = ", ".join([user.mention for user in target_users])
                status_message = f"Waterboard party completed for: {target_mentions}"
                if disconnected_count > 0:
                    status_message += f"\n\n{disconnected_count} user(s) disconnected during the process."

                embed = nextcord.Embed(
                    title="Waterboard Party Complete",
                    description=status_message,
                    color=nextcord.Color.purple()
                )
                
                if interaction.response.is_done(): 
                    await interaction.followup.send(embed=embed, ephemeral=True) 
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)

                if bot_spam_channel:
                    public_embed = nextcord.Embed(
                        description=f"🎉 **WATERBOARD PARTY!** 🎉\n{target_mentions} were all waterboarded by {interaction.user.mention}! 💀💦",
                        color=nextcord.Color.purple()
                    )
                    await bot_spam_channel.send(embed=public_embed)
            except nextcord.errors.NotFound:
                print(f"Error: Interaction not found for follow-up message for waterboard party.")
            except Exception as e:
                print(f"Error sending followup/bot-spam message for waterboard party: {WaterboardCog.s_print_static(str(e))}")

    
    
async def setup(bot):
    cog_instance = WaterboardCog(bot)
    if not cog_instance._tables_created:
        await cog_instance.create_tables()
        cog_instance._tables_created = True
    bot.add_cog(cog_instance)
    print("WaterboardCog has been added to the bot.")