import nextcord
from nextcord.ext import commands, tasks
import aiosqlite
import time

from server_configs.config import GUILD_ID
from server_configs.database_config import DATABASE_PATHS

# Define Powerups
POWERUP_TYPES = {
    "executive_pardon": {
        "name": "Executive Pardon",
        "description": "Grants immunity from the waterboard for 1 hour.",
        "price": 2000,
        "duration_hours": 1,
        "effect_type": "pardon"
    },
    "name_color_red": {
        "name": "Pink @ Color",
        "description": "Change your name color to Red for 12 hours.",
        "price": 1000,
        "duration_hours": 12,
        "effect_type": "role",
        "role_name": "Pink"
    },
    "name_color_blue": {
        "name": "Blue @ Color",
        "description": "Change your name color to Blue for 12 hours.",
        "price": 1000,
        "duration_hours": 12,
        "effect_type": "role",
        "role_name": "Blue"
    }
    # More powerups tbd
}

class PowerupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["powerups"]
        self.check_expired_powerups.start()

    async def cog_load(self):
        await self.create_tables()

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
            waterboard_cog = self.bot.get_cog('WaterboardCog')
            if waterboard_cog and hasattr(waterboard_cog, 'executive_pardon'):
                await waterboard_cog.executive_pardon(user_id, powerup_info["duration_hours"])
                return True
            else:
                print("Error: WaterboardCog or executive_pardon method not found.")
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
        # Pardon duration is managed by WaterboardCog

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
            self.add_item(PowerupSelect(powerup_options))
            self.add_item(QuantitySelect())
            self.add_item(PurchaseButton(self.cog))
        else:
            pass

class PowerupSelect(nextcord.ui.Select):
    def __init__(self, options: list[nextcord.SelectOption]):
        super().__init__(placeholder="Choose a powerup...", min_values=1, max_values=1, options=options, custom_id="powerup_select")

    async def callback(self, interaction: nextcord.Interaction):
        self.view.selected_powerup = self.values[0]
        await interaction.response.defer()

class QuantitySelect(nextcord.ui.Select):
    def __init__(self):
        options = [nextcord.SelectOption(label=str(i), value=str(i)) for i in range(1, 6)]
        super().__init__(placeholder="Select quantity (default 1)...", min_values=1, max_values=1, options=options, custom_id="quantity_select")
    
    async def callback(self, interaction: nextcord.Interaction):
        self.view.selected_quantity = int(self.values[0])
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

        success = await economy_cog.deduct_user_balance(interaction.user.id, total_cost)
        if success:
            for _ in range(selected_quantity):
                await self.powerup_cog_instance.add_powerup_to_inventory(interaction.user.id, selected_powerup_type)
            await interaction.followup.send(f"Purchased {selected_quantity}x {powerup_info['name']} for {total_cost} coins!", ephemeral=True)
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

async def setup(bot):
    cog_instance = PowerupCog(bot)
    await cog_instance.create_tables()
    bot.add_cog(cog_instance)
    print("PowerupCog has been loaded.")
