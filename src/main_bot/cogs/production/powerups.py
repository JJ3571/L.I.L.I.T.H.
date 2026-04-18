import nextcord
from nextcord.ext import commands, tasks
import aiosqlite
import time
from datetime import datetime
import pytz

from main_bot.boot_log import boot_print
from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.database_config import DATABASE_PATHS

# Define Powerups
POWERUP_TYPES = {
    "executive_pardon": {
        "name": "Executive Pardon",
        "description": "Grants immunity from the waterboard for 3 hour.",
        "price": 2000,
        "duration_hours": 3,
        "effect_type": "pardon",
        "storable": True
    },
    "name_color_red": {
        "name": "Pink @ Color",
        "description": "Change your name color to Red for 12 hours.",
        "price": 1000,
        "duration_hours": 12,
        "effect_type": "role",
        "role_name": "Pink",
        "storable": True
    },
    "name_color_blue": {
        "name": "Blue @ Color",
        "description": "Change your name color to Blue for 12 hours.",
        "price": 1000,
        "duration_hours": 12,
        "effect_type": "role",
        "role_name": "Blue",
        "storable": True
    },
    "just_one_more": {
        "name": "Just One More",
        "description": "Forces JJ3571 to play just one more game for 1 hour.",
        "price": 10000,
        "duration_hours": 1,
        "effect_type": "just_one_more",
        "target_user_id": 321888250136363009,  # JJ3571's user ID
        "storable": False  # This powerup is purchased and used immediately
    },
    "art_request": {
        "name": "TheGiftedNut - Art Request",
        "description": "Commission custom artwork from TheGiftedNut.",
        "price": 10000,
        "duration_hours": 0,  # Duration is irrelevant for art requests
        "effect_type": "art_request",
        "target_user_id": 220656152994643969,  # Nut's user ID
        "storable": False  # This powerup is purchased and used immediately
    }
    # More powerups tbd
}

class PowerupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["powerups"]
        self.check_expired_powerups.start()
        self.cleanup_old_purchase_records.start()

    async def cog_load(self):
        await self.create_tables()
        self.daily_art_request_reminder.start()
        
    def cog_unload(self):
        """Stop background tasks when cog unloads"""
        self.cleanup_old_purchase_records.cancel()
        self.daily_art_request_reminder.cancel()

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS powerup_inventory (
                    inventory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    powerup_type TEXT NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS active_powerups (
                    user_id INTEGER NOT NULL,
                    powerup_type TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    PRIMARY KEY (user_id, powerup_type)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS daily_powerup_purchases (
                    user_id INTEGER NOT NULL,
                    powerup_type TEXT NOT NULL,
                    purchase_date TEXT NOT NULL,
                    PRIMARY KEY (user_id, powerup_type, purchase_date)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS art_requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_user_id INTEGER NOT NULL,
                    artist_user_id INTEGER NOT NULL,
                    request_description TEXT NOT NULL,
                    purchase_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    completion_date TEXT,
                    rejection_reason TEXT,
                    amount_paid INTEGER NOT NULL
                )
            ''')
            await db.commit()

    # --- Database Helper Functions ---
    async def add_powerup_to_inventory(self, user_id: int, powerup_type: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO powerup_inventory (user_id, powerup_type) VALUES (?, ?)",
                             (user_id, powerup_type))
            await db.commit()

    async def get_user_inventory(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT powerup_type, COUNT(*) as quantity FROM powerup_inventory WHERE user_id = ? GROUP BY powerup_type",
                                  (user_id,)) as cursor:
                return await cursor.fetchall()
    
    async def get_user_total_inventory_count(self, user_id: int):
        """Get the total number of powerups in a user's inventory"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM powerup_inventory WHERE user_id = ?", (user_id,)) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
    
    async def has_purchased_today(self, user_id: int, powerup_type: str):
        """Check if user has already purchased this powerup type today (PST timezone)"""
        # Get current PST date
        pst = pytz.timezone('US/Pacific')
        current_pst = datetime.now(pst)
        today_date = current_pst.strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM daily_powerup_purchases WHERE user_id = ? AND powerup_type = ? AND purchase_date = ?", 
                                  (user_id, powerup_type, today_date)) as cursor:
                result = await cursor.fetchone()
                return (result[0] if result else 0) > 0
    
    async def record_daily_purchase(self, user_id: int, powerup_type: str):
        """Record that user purchased this powerup type today"""
        # Get current PST date
        pst = pytz.timezone('US/Pacific')
        current_pst = datetime.now(pst)
        today_date = current_pst.strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT OR IGNORE INTO daily_powerup_purchases (user_id, powerup_type, purchase_date) VALUES (?, ?, ?)",
                             (user_id, powerup_type, today_date))
            await db.commit()
    
    def is_user_in_voice_chat(self, user_id: int):
        """Check if a user is currently in a voice channel"""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return False
        
        member = guild.get_member(user_id)
        if not member:
            return False
        
        return member.voice is not None and member.voice.channel is not None
    
    async def create_art_request(self, requester_user_id: int, artist_user_id: int, request_description: str, amount_paid: int):
        """Create a new art request"""
        pst = pytz.timezone('US/Pacific')
        current_pst = datetime.now(pst)
        purchase_date = current_pst.strftime('%Y-%m-%d %H:%M:%S')
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                INSERT INTO art_requests (requester_user_id, artist_user_id, request_description, purchase_date, amount_paid)
                VALUES (?, ?, ?, ?, ?)
            """, (requester_user_id, artist_user_id, request_description, purchase_date, amount_paid)) as cursor:
                request_id = cursor.lastrowid
            await db.commit()
            return request_id
    
    async def get_pending_art_requests(self, artist_user_id: int):
        """Get all pending art requests for an artist"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT request_id, requester_user_id, request_description, purchase_date, amount_paid
                FROM art_requests
                WHERE artist_user_id = ? AND status = 'pending'
                ORDER BY purchase_date ASC
            """, (artist_user_id,)) as cursor:
                return await cursor.fetchall()
    
    async def complete_art_request(self, request_id: int):
        """Mark an art request as completed"""
        pst = pytz.timezone('US/Pacific')
        current_pst = datetime.now(pst)
        completion_date = current_pst.strftime('%Y-%m-%d %H:%M:%S')
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE art_requests
                SET status = 'completed', completion_date = ?
                WHERE request_id = ?
            """, (completion_date, request_id))
            await db.commit()
    
    async def reject_art_request(self, request_id: int, rejection_reason: str):
        """Mark an art request as rejected"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE art_requests
                SET status = 'rejected', rejection_reason = ?
                WHERE request_id = ?
            """, (rejection_reason, request_id))
            await db.commit()
    
    async def get_art_request_details(self, request_id: int):
        """Get details of a specific art request"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT request_id, requester_user_id, artist_user_id, request_description, 
                       purchase_date, status, completion_date, rejection_reason, amount_paid
                FROM art_requests
                WHERE request_id = ?
            """, (request_id,)) as cursor:
                return await cursor.fetchone()

    async def get_active_powerups_for_user(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT powerup_type, end_time FROM active_powerups WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchall()
            
    async def remove_powerup_from_inventory(self, user_id: int, powerup_type: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT inventory_id FROM powerup_inventory WHERE user_id = ? AND powerup_type = ? LIMIT 1", (user_id, powerup_type)) as cursor:
                row = await cursor.fetchone()
                if row:
                    await db.execute("DELETE FROM powerup_inventory WHERE inventory_id = ?", (row[0],))
                    await db.commit()
                    return True
            return False

    async def activate_powerup(self, user_id: int, powerup_type: str, duration_hours: int):
        start_time = int(time.time())
        end_time = start_time + (duration_hours * 3600)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO active_powerups (user_id, powerup_type, start_time, end_time)
                VALUES (?, ?, ?, ?)
            ''', (user_id, powerup_type, start_time, end_time))
            await db.commit()
        return await self.apply_powerup_effect(user_id, powerup_type)

    async def apply_powerup_effect(self, user_id: int, powerup_type: str):
        powerup_info = POWERUP_TYPES.get(powerup_type)
        if not powerup_info: return False

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print(f"Error: Guild {GUILD_ID} not found.")
            return False
        member = guild.get_member(user_id)
        if not member:
            print(f"Error: Member {user_id} not found in guild {GUILD_ID}.")
            return False

        if powerup_info["effect_type"] == "pardon":
            waterboard_cog = self.bot.get_cog('WaterboardCog3')
            if waterboard_cog and hasattr(waterboard_cog, 'executive_pardon'):
                try:
                    await waterboard_cog.executive_pardon(user_id, powerup_info["duration_hours"])
                    return True
                except Exception as e:
                    print(f"Error calling executive_pardon: {e}")
                    return False
            else:
                print("Error: WaterboardCog3 or executive_pardon method not found.")
                return False
        elif powerup_info["effect_type"] == "role":
            role_name = powerup_info["role_name"]
            role = nextcord.utils.get(guild.roles, name=role_name)
            if role:
                try:
                    await member.add_roles(role, reason=f"Activated {powerup_info['name']} powerup")
                    return True
                except nextcord.Forbidden:
                    print(f"Error: Bot lacks permissions to assign role '{role_name}'.")
                    return False
                except nextcord.HTTPException as e:
                    print(f"Error: Failed to assign role '{role_name}': {e}")
                    return False
            else:
                print(f"Error: Role '{role_name}' not found on server.")
                return False
        return False

    async def remove_powerup_effect(self, user_id: int, powerup_type: str):
        powerup_info = POWERUP_TYPES.get(powerup_type)
        if not powerup_info: return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild: return
        member = guild.get_member(user_id)
        if not member: return

        if powerup_info["effect_type"] == "role":
            role_name = powerup_info["role_name"]
            role = nextcord.utils.get(guild.roles, name=role_name)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason=f"{powerup_info['name']} powerup expired")
                    print(f"Removed role '{role_name}' from {member.display_name} (Powerup expired).")
                except nextcord.Forbidden:
                    print(f"Error: Bot lacks permissions to remove role '{role_name}'.")
                except nextcord.HTTPException as e:
                    print(f"Error: Failed to remove role '{role_name}': {e}")
        # Pardon duration is managed by WaterboardCog3

    # --- Slash Commands ---
    @nextcord.slash_command(name="powerups", description="Manage your powerups", guild_ids=[GUILD_ID])
    async def powerups_group(self, interaction: nextcord.Interaction):
        pass

    @powerups_group.subcommand(name="purchase", description="Purchase powerups from the shop.")
    async def purchase_powerup(self, interaction: nextcord.Interaction):
        view = PowerupPurchaseView(self.bot, interaction.user.id, self)
        embed = nextcord.Embed(title="Powerup Shop", description="Select a powerup and quantity to purchase.", color=nextcord.Color.blue())
        if not POWERUP_TYPES:
            embed.description = "The shop is currently empty."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        for p_type, p_info in POWERUP_TYPES.items():
            embed.add_field(name=f"{p_info['name']} ({p_info['price']} coins)", value=p_info['description'], inline=False)
        
        if not view.children: # No powerups to select
             embed.description = "There are no powerups available for purchase at the moment."
             await interaction.response.send_message(embed=embed, ephemeral=True)
             return

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @powerups_group.subcommand(name="inventory", description="View and use your owned powerups.")
    async def inventory_powerup(self, interaction: nextcord.Interaction):
        user_inventory = await self.get_user_inventory(interaction.user.id)
        
        embed = nextcord.Embed(title=f"{interaction.user.display_name}'s Powerup Inventory", color=nextcord.Color.green())
        view = PowerupInventoryView(self.bot, interaction.user.id, self, user_inventory)

        if not user_inventory or not view.children: # No items or no buttons generated
            embed.description = "Your inventory is empty."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        for powerup_type, quantity in user_inventory:
            if quantity > 0:
                powerup_info = POWERUP_TYPES.get(powerup_type)
                if powerup_info:
                    embed.add_field(name=f"{powerup_info['name']} (x{quantity})", value=powerup_info['description'], inline=False)
        
        if not embed.fields: # Should be caught by previous check, but as a safeguard
            embed.description = "Your inventory is empty or contains no recognized powerups."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @powerups_group.subcommand(name="active", description="View and manage your active powerups.")
    async def active_powerups_command(self, interaction: nextcord.Interaction):
        user_id = interaction.user.id
        active_powerups_data = await self.get_active_powerups_for_user(user_id)
        current_time = int(time.time())

        embed = nextcord.Embed(title=f"{interaction.user.display_name}'s Active Powerups", color=nextcord.Color.purple())
        
        if not active_powerups_data:
            embed.description = "You have no active powerups."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = ActivePowerupsView(self.bot, user_id, self, active_powerups_data)

        for powerup_type, end_time in active_powerups_data:
            powerup_info = POWERUP_TYPES.get(powerup_type)
            if powerup_info:
                remaining_seconds = end_time - current_time
                if remaining_seconds > 0:
                    # Format remaining time (e.g., Xh Ym Zs)
                    hours, remainder = divmod(remaining_seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    time_str = ""
                    if hours > 0:
                        time_str += f"{hours}h "
                    if minutes > 0:
                        time_str += f"{minutes}m "
                    if seconds > 0 or not time_str: # Show seconds if it's the only unit or if other units are zero
                        time_str += f"{seconds}s"
                    
                    embed.add_field(
                        name=f"{powerup_info['name']}",
                        value=f"Ends in: {time_str.strip()}",
                        inline=False
                    )
                else:
                    # This case should ideally be handled by check_expired_powerups,
                    # but good to have a fallback display.
                    embed.add_field(
                        name=f"{powerup_info['name']}",
                        value="Expired (pending removal)",
                        inline=False
                    )
            else: # Should not happen if DB is consistent with POWERUP_TYPES
                embed.add_field(name=f"Unknown Powerup ({powerup_type})", value="Data error.", inline=False)
        
        if not embed.fields: # If all powerups were somehow filtered out or unknown
            embed.description = "You have no active powerups to display."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @powerups_group.subcommand(name="art-requests", description="Manage art requests (TheGiftedNut only)")
    async def art_requests_command(self, interaction: nextcord.Interaction):
        """Admin command for Nut to manage art requests"""
        nut_user_id = 220656152994643969  # Nut's user ID
        
        if interaction.user.id != nut_user_id:
            await interaction.response.send_message("⛔ This command is only available to TheGiftedNut!", ephemeral=True)
            return
        
        # Get all pending art requests
        pending_requests = await self.get_pending_art_requests(nut_user_id)
        
        if not pending_requests:
            embed = nextcord.Embed(
                title="🎨 Art Request Management",
                description="No pending art requests at this time!",
                color=nextcord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = nextcord.Embed(
            title="🎨 Art Request Management",
            description=f"You have {len(pending_requests)} pending art request(s)",
            color=nextcord.Color.purple()
        )
        
        # Show details of up to 5 requests
        for i, request in enumerate(pending_requests[:5]):
            request_id, requester_user_id, request_description, purchase_date, amount_paid = request
            guild = interaction.guild
            requester = guild.get_member(requester_user_id) if guild else None
            requester_name = requester.display_name if requester else f"User {requester_user_id}"
            
            embed.add_field(
                name=f"Request #{request_id} - {requester_name}",
                value=f"💰 {amount_paid} 🪙\n📅 {purchase_date[:10]}\n📝 {request_description[:150]}{'...' if len(request_description) > 150 else ''}",
                inline=False
            )
        
        if len(pending_requests) > 5:
            embed.add_field(
                name="📋 Additional Requests",
                value=f"+ {len(pending_requests) - 5} more pending requests",
                inline=False
            )
        
        # Create management view for the oldest request
        if pending_requests:
            oldest_request = pending_requests[0]  # First in list is oldest
            request_details = await self.get_art_request_details(oldest_request[0])
            if request_details:
                view = ArtRequestManagementView(self, request_details)
                embed.set_footer(text="Use the buttons below to manage the oldest request.")
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Background Task ---
    @tasks.loop(minutes=1)
    async def check_expired_powerups(self):
        current_time = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id, powerup_type FROM active_powerups WHERE end_time <= ?", (current_time,)) as cursor:
                expired = await cursor.fetchall()
            
            if expired:
                for user_id, powerup_type in expired:
                    print(f"Powerup {powerup_type} for user {user_id} has expired. Removing effect.")
                    await self.remove_powerup_effect(user_id, powerup_type)
                    await db.execute("DELETE FROM active_powerups WHERE user_id = ? AND powerup_type = ?", (user_id, powerup_type))
                await db.commit()

    @check_expired_powerups.before_loop
    async def before_check_expired_powerups(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)  # Run once per day
    async def cleanup_old_purchase_records(self):
        """Clean up purchase records older than 7 days to keep database tidy"""
        from datetime import timedelta
        pst = pytz.timezone('US/Pacific')
        current_pst = datetime.now(pst)
        cutoff_date = (current_pst - timedelta(days=7)).strftime('%Y-%m-%d')  # 7 days ago
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM daily_powerup_purchases WHERE purchase_date < ?", (cutoff_date,))
            await db.commit()
    
    @cleanup_old_purchase_records.before_loop
    async def before_cleanup_old_purchase_records(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)  # Run once per day
    async def daily_art_request_reminder(self):
        """Send daily reminder to Nut about pending art requests"""
        nut_user_id = 220656152994643969  # Nut's user ID
        
        # Get pending art requests for Nut
        pending_requests = await self.get_pending_art_requests(nut_user_id)
        
        if not pending_requests:
            return  # No pending requests, no reminder needed
        
        # Get bot spam channel
        try:
            from main_bot.server_configs.config import bot_spam_id
            bot_spam_channel = self.bot.get_channel(bot_spam_id)
            if not bot_spam_channel:
                return
        except ImportError:
            return
        
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return
        
        nut_user = guild.get_member(nut_user_id)
        if not nut_user:
            return
        
        # Create reminder embed
        embed = nextcord.Embed(
            title="🎨 Daily Art Request Reminder",
            description=f"{nut_user.mention}, you have {len(pending_requests)} pending art request(s)!",
            color=nextcord.Color.purple()
        )
        
        # Add details for each request (limit to 5 for readability)
        for i, request in enumerate(pending_requests[:5]):
            request_id, requester_user_id, request_description, purchase_date, amount_paid = request
            requester = guild.get_member(requester_user_id)
            requester_name = requester.display_name if requester else f"User {requester_user_id}"
            
            embed.add_field(
                name=f"Request #{request_id} - {requester_name}",
                value=f"💰 {amount_paid} 🪙\n📅 {purchase_date[:10]}\n📝 {request_description[:100]}{'...' if len(request_description) > 100 else ''}",
                inline=False
            )
        
        if len(pending_requests) > 5:
            embed.add_field(
                name="📋 Additional Requests",
                value=f"+ {len(pending_requests) - 5} more pending requests",
                inline=False
            )
        
        # Create management view for the most recent request
        if pending_requests:
            most_recent = pending_requests[0]  # They're ordered by purchase_date ASC, so first is oldest
            request_details = await self.get_art_request_details(most_recent[0])
            if request_details:
                view = ArtRequestManagementView(self, request_details)
                embed.set_footer(text="Use the buttons below to manage the oldest request, or use /powerups art-requests for full management.")
                await bot_spam_channel.send(embed=embed, view=view)
            else:
                await bot_spam_channel.send(embed=embed)
        else:
            await bot_spam_channel.send(embed=embed)
    
    @daily_art_request_reminder.before_loop
    async def before_daily_art_request_reminder(self):
        await self.bot.wait_until_ready()

# --- UI Views ---
class PowerupPurchaseView(nextcord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int, cog: PowerupCog, timeout=180):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.user_id = user_id
        self.cog = cog
        self.selected_powerup = None
        self.selected_quantity = 1

        powerup_options = []
        for p_type, p_info in POWERUP_TYPES.items():
            powerup_options.append(nextcord.SelectOption(
                label=f"{p_info['name']} ({p_info['price']} coins)",
                value=p_type,
                description=p_info['description'][:100]
            ))
        
        if powerup_options:
            powerup_select = PowerupSelect(powerup_options)
            self.add_item(powerup_select)
            
            # Only add quantity selector if there are storable powerups
            has_storable = any(POWERUP_TYPES.get(p_type, {}).get("storable", True) for p_type in POWERUP_TYPES.keys())
            if has_storable:
                self.add_item(QuantitySelect())
            
            self.add_item(PurchaseButton(self.cog))
        else:
            pass

class PowerupSelect(nextcord.ui.Select):
    def __init__(self, options: list[nextcord.SelectOption]):
        super().__init__(placeholder="Choose a powerup...", min_values=1, max_values=1, options=options, custom_id="powerup_select")

    async def callback(self, interaction: nextcord.Interaction):
        self.view.selected_powerup = self.values[0]
        
        # For non-storable powerups, set quantity to 1 and disable quantity selector
        powerup_info = POWERUP_TYPES.get(self.values[0])
        if powerup_info and not powerup_info.get("storable", True):
            self.view.selected_quantity = 1
            # Disable quantity selector for non-storable items
            for item in self.view.children:
                if isinstance(item, QuantitySelect):
                    item.disabled = True
        else:
            # Re-enable quantity selector for storable items
            for item in self.view.children:
                if isinstance(item, QuantitySelect):
                    item.disabled = False
        
        # Update the placeholder to show current selection
        self.placeholder = f"{powerup_info['name']}" if powerup_info else "Choose a powerup..."
        
        # Update quantity selector placeholder too
        for item in self.view.children:
            if isinstance(item, QuantitySelect):
                item.placeholder = f"Quantity: {self.view.selected_quantity}"
        
        # Update the embed to show the selected powerup
        embed = nextcord.Embed(title="Powerup Shop", color=nextcord.Color.blue())
        
        if powerup_info:
            embed.description = f"**Selected:** {powerup_info['name']} ({powerup_info['price']} coins)\n{powerup_info['description']}"
            if not powerup_info.get("storable", True):
                embed.description += "\n\n⚠️ This powerup activates immediately upon purchase."
            
            # Show total cost if quantity > 1
            if self.view.selected_quantity > 1:
                total_cost = powerup_info['price'] * self.view.selected_quantity
                embed.add_field(name="Total Cost", value=f"{total_cost} coins (x{self.view.selected_quantity})", inline=True)
        
        # Still show all available powerups
        for p_type, p_info in POWERUP_TYPES.items():
            embed.add_field(name=f"{p_info['name']} ({p_info['price']} coins)", value=p_info['description'], inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self.view)

class QuantitySelect(nextcord.ui.Select):
    def __init__(self):
        options = [nextcord.SelectOption(label=str(i), value=str(i)) for i in range(1, 4)]  # 1, 2, 3 (max inventory is 3)
        super().__init__(placeholder="Select quantity (default 1)...", min_values=1, max_values=1, options=options, custom_id="quantity_select")
    
    async def callback(self, interaction: nextcord.Interaction):
        self.view.selected_quantity = int(self.values[0])
        
        # Update the placeholder to show current selection
        self.placeholder = f"Quantity: {self.view.selected_quantity}"
        
        # Update the embed if a powerup is selected
        if self.view.selected_powerup:
            powerup_info = POWERUP_TYPES.get(self.view.selected_powerup)
            if powerup_info:
                embed = nextcord.Embed(title="Powerup Shop", color=nextcord.Color.blue())
                embed.description = f"**Selected:** {powerup_info['name']} ({powerup_info['price']} coins)\n{powerup_info['description']}"
                
                if not powerup_info.get("storable", True):
                    embed.description += "\n\n⚠️ This powerup activates immediately upon purchase."
                
                # Show total cost
                total_cost = powerup_info['price'] * self.view.selected_quantity
                embed.add_field(name="Total Cost", value=f"{total_cost} coins (x{self.view.selected_quantity})", inline=True)
                
                # Show all available powerups
                for p_type, p_info in POWERUP_TYPES.items():
                    embed.add_field(name=f"{p_info['name']} ({p_info['price']} coins)", value=p_info['description'], inline=False)
                
                await interaction.response.edit_message(embed=embed, view=self.view)
                return
        
        await interaction.response.defer()

class PurchaseButton(nextcord.ui.Button):
    def __init__(self, powerup_cog_instance: PowerupCog):
        super().__init__(label="Purchase", style=nextcord.ButtonStyle.green, custom_id="purchase_button")
        self.powerup_cog_instance = powerup_cog_instance

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.view.selected_powerup:
            await interaction.followup.send("Please select a powerup first.", ephemeral=True)
            return
        
        selected_powerup_type = self.view.selected_powerup
        selected_quantity = self.view.selected_quantity

        powerup_info = POWERUP_TYPES.get(selected_powerup_type)
        if not powerup_info:
            await interaction.followup.send("Invalid powerup selected.", ephemeral=True)
            return

        economy_cog = self.powerup_cog_instance.bot.get_cog('Economy')
        if not economy_cog or not hasattr(economy_cog, 'get_user_balance') or not hasattr(economy_cog, 'deduct_user_balance'):
            await interaction.followup.send("Economy system is unavailable. Cannot complete purchase.", ephemeral=True)
            return

        total_cost = powerup_info["price"] * selected_quantity
        user_balance = await economy_cog.get_user_balance(interaction.user.id)

        if user_balance is None or user_balance < total_cost:
            await interaction.followup.send(f"You need {total_cost} coins, but have {user_balance or 0}.", ephemeral=True)
            return

        # Handle non-storable powerups (like "Just one more")
        if not powerup_info.get("storable", True):
            # Special handling for just_one_more powerup
            if selected_powerup_type == "just_one_more":
                # Check if user has already purchased this powerup today
                if await self.powerup_cog_instance.has_purchased_today(interaction.user.id, selected_powerup_type):
                    embed = nextcord.Embed(
                        title="⏰ Daily Limit Reached",
                        description=f"You can only purchase **Just One More** once per day (PST timezone)!\n\nNext purchase available tomorrow at midnight PST.",
                        color=nextcord.Color.red()
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Check if JJ3571 is in a voice chat
                target_user_id = powerup_info["target_user_id"]
                if not self.powerup_cog_instance.is_user_in_voice_chat(target_user_id):
                    target_user = interaction.guild.get_member(target_user_id)
                    target_name = target_user.display_name if target_user else "JJ3571"
                    
                    embed = nextcord.Embed(
                        title="JJ Not Available",
                        description=f"{target_name} must be in a voice channel to play just one more game!\n\nPlease wait until they're active and in voice chat.",
                        color=nextcord.Color.orange()
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                success = await economy_cog.deduct_user_balance(interaction.user.id, total_cost)
                if success:
                    # Record the daily purchase
                    await self.powerup_cog_instance.record_daily_purchase(interaction.user.id, selected_powerup_type)
                    
                    # Add money to JJ3571's trust fund
                    await economy_cog.add_to_trust_fund(powerup_info["target_user_id"], total_cost)
                    
                    # Send notification embed
                    target_user = interaction.guild.get_member(powerup_info["target_user_id"])
                    if target_user:
                        voice_channel_name = target_user.voice.channel.name if target_user.voice and target_user.voice.channel else "Unknown"
                        embed = nextcord.Embed(
                            title="🎮 Just One More!",
                            description=f"{interaction.user.mention} has purchased **Just One More** for {target_user.mention}!\n\nTime to play just one more game! ⏰ 1 hour duration\n🎧 Currently in: **{voice_channel_name}**",
                            color=nextcord.Color.orange()
                        )
                        embed.set_footer(text=f"💰 {total_cost} coins added to {target_user.display_name}'s trust fund")
                        
                        # Send to bot spam channel if available
                        try:
                            from main_bot.server_configs.config import bot_spam_id
                            bot_spam_channel = interaction.guild.get_channel(bot_spam_id)
                            if bot_spam_channel:
                                await bot_spam_channel.send(embed=embed)
                        except ImportError:
                            pass  # If bot_spam_id not available, skip public notification
                        
                        await interaction.followup.send(f"Successfully purchased {powerup_info['name']}! {target_user.mention} has been notified and {total_cost} coins added to their trust fund.", ephemeral=True)
                    else:
                        await interaction.followup.send(f"Purchased {powerup_info['name']} for {total_cost} coins! Target user not found but trust fund updated.", ephemeral=True)
                    
                    self.view.stop()
                else:
                    await interaction.followup.send("Transaction failed. Please try again.", ephemeral=True)
            elif selected_powerup_type == "art_request":
                # Show art request modal for user to input their request
                modal = ArtRequestModal(self.powerup_cog_instance, economy_cog, powerup_info, total_cost)
                
                # Since we already deferred, we need to use a different approach
                # Create a simple view with a button to trigger the modal
                view = ArtRequestTriggerView(modal)
                embed = nextcord.Embed(
                    title="🎨 Art Request - TheGiftedNut",
                    description=f"Click the button below to submit your art request.\n\n**Cost:** {total_cost} 🪙",
                    color=nextcord.Color.purple()
                )
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                self.view.stop()
                return
            else:
                await interaction.followup.send("This powerup type is not yet implemented.", ephemeral=True)
            return

        # Check inventory limit (max 3 powerups total) - only for storable powerups
        current_inventory_count = await self.powerup_cog_instance.get_user_total_inventory_count(interaction.user.id)
        if current_inventory_count + selected_quantity > 3:
            remaining_slots = max(0, 3 - current_inventory_count)
            if remaining_slots == 0:
                await interaction.followup.send("Your inventory is full! You can only hold 3 powerups at a time. Use some powerups first.", ephemeral=True)
            else:
                await interaction.followup.send(f"You can only purchase {remaining_slots} more powerup(s). Your inventory limit is 3 total.", ephemeral=True)
            return

        success = await economy_cog.deduct_user_balance(interaction.user.id, total_cost)
        
        if success:
            for _ in range(selected_quantity):
                await self.powerup_cog_instance.add_powerup_to_inventory(interaction.user.id, selected_powerup_type)
            # Create success message with optional activate button
            success_embed = nextcord.Embed(
                title="✅ Purchase Successful!",
                description=f"Purchased {selected_quantity}x **{powerup_info['name']}** for {total_cost} coins!",
                color=nextcord.Color.green()
            )
            
            # Add activate button for storable powerups
            if powerup_info.get("storable", True):
                activate_view = ActivateNowView(selected_powerup_type, powerup_info['name'], self.powerup_cog_instance)
                await interaction.followup.send(embed=success_embed, view=activate_view, ephemeral=True)
            else:
                await interaction.followup.send(embed=success_embed, ephemeral=True)
            
            self.view.stop()
        else:
            await interaction.followup.send("Transaction failed. Please try again.", ephemeral=True)

class PowerupInventoryView(nextcord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int, cog: PowerupCog, inventory_items: list, timeout=180):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.user_id = user_id
        self.cog = cog
        
        for powerup_type, quantity in inventory_items:
            if quantity > 0:
                powerup_info = POWERUP_TYPES.get(powerup_type)
                if powerup_info:
                    self.add_item(UsePowerupButton(powerup_type, powerup_info['name'], self.cog))

class ActivateNowView(nextcord.ui.View):
    def __init__(self, powerup_type: str, powerup_name: str, cog: PowerupCog, timeout=300):
        super().__init__(timeout=timeout)
        self.add_item(ActivateNowButton(powerup_type, powerup_name, cog))

class ActivateNowButton(nextcord.ui.Button):
    def __init__(self, powerup_type: str, powerup_name: str, cog: PowerupCog):
        super().__init__(label=f"🚀 Activate {powerup_name}", style=nextcord.ButtonStyle.success, custom_id=f"activate_{powerup_type}")
        self.powerup_type = powerup_type
        self.cog = cog

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Check if user still has this powerup in inventory
        inventory = await self.cog.get_user_inventory(interaction.user.id)
        has_powerup = any(ptype == self.powerup_type and qty > 0 for ptype, qty in inventory)

        if not has_powerup:
            await interaction.followup.send(f"You no longer have {POWERUP_TYPES[self.powerup_type]['name']} in your inventory.", ephemeral=True)
            return

        # Remove one from inventory
        removed = await self.cog.remove_powerup_from_inventory(interaction.user.id, self.powerup_type)
        if not removed:
            await interaction.followup.send("Unable to remove powerup from inventory.", ephemeral=True)
            return

        # Apply the powerup effect
        success = await self.cog.apply_powerup_effect(interaction.user.id, self.powerup_type)
        if success:
            powerup_info = POWERUP_TYPES[self.powerup_type]
            if powerup_info.get("duration"):
                await interaction.followup.send(f"✅ Successfully activated {powerup_info['name']}! Duration: {powerup_info['duration']}", ephemeral=True)
            else:
                await interaction.followup.send(f"✅ Successfully activated {powerup_info['name']}!", ephemeral=True)
            
            # Disable this button since it was used
            self.disabled = True
            self.label = "✅ Activated!"
            self.style = nextcord.ButtonStyle.secondary
            try:
                await interaction.edit_original_message(view=self.view)
            except:
                pass  # In case the message can't be edited
        else:
            # If activation failed, add the powerup back to inventory
            await self.cog.add_powerup_to_inventory(interaction.user.id, self.powerup_type)
            await interaction.followup.send("Failed to activate powerup. It has been returned to your inventory.", ephemeral=True)

class UsePowerupButton(nextcord.ui.Button):
    def __init__(self, powerup_type: str, powerup_name: str, cog: PowerupCog):
        super().__init__(label=f"Use {powerup_name}", style=nextcord.ButtonStyle.primary, custom_id=f"use_{powerup_type}")
        self.powerup_type = powerup_type
        self.cog = cog

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        inventory = await self.cog.get_user_inventory(interaction.user.id)
        has_powerup = any(ptype == self.powerup_type and qty > 0 for ptype, qty in inventory)

        if not has_powerup:
            await interaction.followup.send(f"You no longer have {POWERUP_TYPES[self.powerup_type]['name']}.", ephemeral=True)
            return

        removed = await self.cog.remove_powerup_from_inventory(interaction.user.id, self.powerup_type)
        if not removed:
            await interaction.followup.send(f"Failed to use. It might have been used already.", ephemeral=True)
            return

        powerup_info = POWERUP_TYPES.get(self.powerup_type)
        activated = await self.cog.activate_powerup(interaction.user.id, self.powerup_type, powerup_info["duration_hours"])

        if activated:
            await interaction.followup.send(f"Used {powerup_info['name']}! Lasts {powerup_info['duration_hours']} hour(s).", ephemeral=True)
            
            # Refresh the inventory message by re-generating it
            new_inventory_items = await self.cog.get_user_inventory(interaction.user.id)
            new_embed = nextcord.Embed(title=f"{interaction.user.display_name}'s Powerup Inventory", color=nextcord.Color.green())
            new_view = PowerupInventoryView(self.cog.bot, interaction.user.id, self.cog, new_inventory_items)

            if not new_inventory_items or not new_view.children:
                new_embed.description = "Your inventory is now empty."
                await interaction.edit_original_message(embed=new_embed, view=None)
            else:
                for p_type, quantity in new_inventory_items:
                    if quantity > 0:
                        p_info = POWERUP_TYPES.get(p_type)
                        if p_info:
                            new_embed.add_field(name=f"{p_info['name']} (x{quantity})", value=p_info['description'], inline=False)
                if not new_embed.fields: # Safeguard
                     new_embed.description = "Your inventory is now empty."
                     await interaction.edit_original_message(embed=new_embed, view=None)
                else:
                    await interaction.edit_original_message(embed=new_embed, view=new_view)
        else:
            await self.cog.add_powerup_to_inventory(interaction.user.id, self.powerup_type)
            await interaction.followup.send(f"Failed to activate {powerup_info['name']}. Returned to inventory. (Check bot console for errors like missing roles/permissions).", ephemeral=True)

class ActivePowerupsView(nextcord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: int, cog: PowerupCog, active_powerups: list, timeout=180):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.user_id = user_id
        self.cog = cog
        current_time = int(time.time())

        for powerup_type, end_time in active_powerups:
            if end_time > current_time: # Only add buttons for genuinely active ones
                powerup_info = POWERUP_TYPES.get(powerup_type)
                if powerup_info:
                    self.add_item(DeactivatePowerupButton(powerup_type, powerup_info['name'], self.cog))

class DeactivatePowerupButton(nextcord.ui.Button):
    def __init__(self, powerup_type: str, powerup_name: str, cog: PowerupCog):
        super().__init__(label=f"Deactivate {powerup_name}", style=nextcord.ButtonStyle.red, custom_id=f"deactivate_{powerup_type}")
        self.powerup_type = powerup_type
        self.cog = cog

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        powerup_info = POWERUP_TYPES.get(self.powerup_type)

        if not powerup_info:
            await interaction.followup.send("Could not find information for this powerup to deactivate.", ephemeral=True)
            return

        # Attempt to remove the effect
        await self.cog.remove_powerup_effect(user_id, self.powerup_type)

        # Remove from active_powerups table
        async with aiosqlite.connect(self.cog.db_path) as db:
            await db.execute("DELETE FROM active_powerups WHERE user_id = ? AND powerup_type = ?",
                             (user_id, self.powerup_type))
            await db.commit()

        await interaction.followup.send(f"{powerup_info['name']} has been deactivated.", ephemeral=True)

        # Refresh the active powerups message
        active_powerups_data = await self.cog.get_active_powerups_for_user(user_id)
        current_time = int(time.time())
        new_embed = nextcord.Embed(title=f"{interaction.user.display_name}'s Active Powerups", color=nextcord.Color.purple())
        
        if not active_powerups_data:
            new_embed.description = "You have no active powerups."
            await interaction.edit_original_message(embed=new_embed, view=None)
            return

        new_view = ActivePowerupsView(self.cog.bot, user_id, self.cog, active_powerups_data)

        for p_type, end_time in active_powerups_data:
            p_info = POWERUP_TYPES.get(p_type)
            if p_info:
                remaining_seconds = end_time - current_time
                if remaining_seconds > 0:
                    hours, remainder = divmod(remaining_seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    time_str = ""
                    if hours > 0: time_str += f"{hours}h "
                    if minutes > 0: time_str += f"{minutes}m "
                    if seconds > 0 or not time_str: time_str += f"{seconds}s"
                    new_embed.add_field(name=f"{p_info['name']}", value=f"Ends in: {time_str.strip()}", inline=False)
                else:
                    new_embed.add_field(name=f"{p_info['name']}", value="Expired (pending removal)", inline=False)
        
        if not new_embed.fields:
            new_embed.description = "You have no active powerups to display."
            await interaction.edit_original_message(embed=new_embed, view=None)
            return
        
        if not new_view.children: # If all buttons were removed because all powerups expired/deactivated
            await interaction.edit_original_message(embed=new_embed, view=None)
        else:
            await interaction.edit_original_message(embed=new_embed, view=new_view)

class ArtRequestTriggerView(nextcord.ui.View):
    def __init__(self, modal: 'ArtRequestModal'):
        super().__init__(timeout=300)
        self.modal = modal

    @nextcord.ui.button(label="📝 Submit Art Request", style=nextcord.ButtonStyle.primary)
    async def submit_request(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(self.modal)

class ArtRequestModal(nextcord.ui.Modal):
    def __init__(self, powerup_cog_instance: PowerupCog, economy_cog, powerup_info: dict, total_cost: int):
        super().__init__("Art Request - TheGiftedNut", timeout=300)  # 5 minute timeout
        self.powerup_cog_instance = powerup_cog_instance
        self.economy_cog = economy_cog
        self.powerup_info = powerup_info
        self.total_cost = total_cost

        self.request_description = nextcord.ui.TextInput(
            label="Art Request Description",
            placeholder="Describe your custom artwork request in detail...",
            style=nextcord.TextInputStyle.paragraph,
            max_length=2000,
            required=True
        )
        self.add_item(self.request_description)

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Deduct payment
        success = await self.economy_cog.deduct_user_balance(interaction.user.id, self.total_cost)
        if not success:
            await interaction.followup.send("Transaction failed. Please try again.", ephemeral=True)
            return
        
        # Create art request
        request_id = await self.powerup_cog_instance.create_art_request(
            requester_user_id=interaction.user.id,
            artist_user_id=self.powerup_info["target_user_id"],
            request_description=self.request_description.value,
            amount_paid=self.total_cost
        )
        
        # Send confirmation to purchaser
        embed = nextcord.Embed(
            title="🎨 Art Request Submitted",
            description=f"Your art request has been submitted to TheGiftedNut!\n\n**Request ID:** #{request_id}\n**Amount:** {self.total_cost} 🪙",
            color=nextcord.Color.purple()
        )
        embed.add_field(name="Your Request", value=self.request_description.value[:1000] + ("..." if len(self.request_description.value) > 1000 else ""), inline=False)
        embed.set_footer(text="TheGiftedNut will be notified and can accept or decline your request.")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        # Send notification to bot spam channel
        try:
            from main_bot.server_configs.config import bot_spam_id
            bot_spam_channel = interaction.guild.get_channel(bot_spam_id)
            if bot_spam_channel:
                artist_user = interaction.guild.get_member(self.powerup_info["target_user_id"])
                public_embed = nextcord.Embed(
                    title="🎨 New Art Request!",
                    description=f"{interaction.user.mention} has commissioned art from {artist_user.mention if artist_user else 'TheGiftedNut'}!",
                    color=nextcord.Color.purple()
                )
                public_embed.add_field(name="Request ID", value=f"#{request_id}", inline=True)
                public_embed.add_field(name="Commission Value", value=f"{self.total_cost} 🪙", inline=True)
                await bot_spam_channel.send(embed=public_embed)
        except ImportError:
            pass

class ArtRequestManagementView(nextcord.ui.View):
    def __init__(self, powerup_cog_instance: PowerupCog, request_details: tuple):
        super().__init__(timeout=None)  # Persistent view
        self.powerup_cog_instance = powerup_cog_instance
        self.request_id, self.requester_user_id, self.artist_user_id, self.request_description, \
        self.purchase_date, self.status, self.completion_date, self.rejection_reason, self.amount_paid = request_details

    @nextcord.ui.button(label="✅ Complete Request", style=nextcord.ButtonStyle.green)
    async def complete_request(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Only allow the artist (Nut) to complete requests
        if interaction.user.id != self.artist_user_id:
            await interaction.response.send_message("Only TheGiftedNut can complete art requests.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Complete the request
        await self.powerup_cog_instance.complete_art_request(self.request_id)
        
        # Add money to artist's trust fund
        economy_cog = self.powerup_cog_instance.bot.get_cog('Economy')
        if economy_cog:
            await economy_cog.add_to_trust_fund(self.artist_user_id, self.amount_paid)
        
        # Send completion notification
        embed = nextcord.Embed(
            title="✅ Art Request Completed",
            description=f"Request #{self.request_id} has been marked as completed!",
            color=nextcord.Color.green()
        )
        embed.add_field(name="Commission Value", value=f"{self.amount_paid} 🪙 → Trust Fund", inline=True)
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.followup.send(embed=embed)
        await interaction.edit_original_message(view=self)

    @nextcord.ui.button(label="❌ Reject Request", style=nextcord.ButtonStyle.red)
    async def reject_request(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Only allow the artist (Nut) to reject requests
        if interaction.user.id != self.artist_user_id:
            await interaction.response.send_message("Only TheGiftedNut can reject art requests.", ephemeral=True)
            return
        
        # Show rejection reason modal
        modal = ArtRejectionModal(self.powerup_cog_instance, self.request_id, self.requester_user_id, self.amount_paid)
        await interaction.response.send_modal(modal)

class ArtRejectionModal(nextcord.ui.Modal):
    def __init__(self, powerup_cog_instance: PowerupCog, request_id: int, requester_user_id: int, amount_paid: int):
        super().__init__("Reject Art Request", timeout=300)
        self.powerup_cog_instance = powerup_cog_instance
        self.request_id = request_id
        self.requester_user_id = requester_user_id
        self.amount_paid = amount_paid

        self.rejection_reason = nextcord.ui.TextInput(
            label="Rejection Reason",
            placeholder="Explain why this request cannot be completed...",
            style=nextcord.TextInputStyle.paragraph,
            max_length=500,
            required=True
        )
        self.add_item(self.rejection_reason)

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        
        # Reject the request
        await self.powerup_cog_instance.reject_art_request(self.request_id, self.rejection_reason.value)
        
        # Refund the requester
        economy_cog = self.powerup_cog_instance.bot.get_cog('Economy')
        if economy_cog:
            await economy_cog.update_balance(self.requester_user_id, self.amount_paid)
        
        # Send rejection notification
        embed = nextcord.Embed(
            title="❌ Art Request Rejected",
            description=f"Request #{self.request_id} has been rejected and refunded.",
            color=nextcord.Color.red()
        )
        embed.add_field(name="Reason", value=self.rejection_reason.value, inline=False)
        embed.add_field(name="Refund", value=f"{self.amount_paid} 🪙 returned to requester", inline=True)
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    cog_instance = PowerupCog(bot)
    await cog_instance.create_tables()
    bot.add_cog(cog_instance)
    boot_print("PowerupCog has been loaded.")
