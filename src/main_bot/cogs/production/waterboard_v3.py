"""
What changed with v3: Rate-limit-friendly implementation using a prepopulated Waterboard category.
- No channel creation/deletion - category is hidden/shown instead
- /waterboard, /enhanced-waterboard, /waterboard-party use premade channels
- /waterboard-party uses the first 2 water channels only: everyone → channel 1 → channel 2 → back to origin
"""
import nextcord
from nextcord.ext import commands, tasks
import asyncio
import time
import aiosqlite
from asyncio import Semaphore

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import GUILD_ID, waterboard_category_id
from main_bot.server_configs.config import bot_spam_id, admin_user_ids
from main_bot.cogs.production.economy import Economy
from main_bot.server_configs.database_config import DATABASE_PATHS

# Default water channel names (10 channels for /waterboard and /enhanced-waterboard)
WATER_CHANNEL_NAMES = [
    "💧🌊💧🌊",
    "🌊🐟🌊💧",
    "💧💧💧🏞️",
    "💧🐟💧🐟",
    "💧💧🐟💧",
    "🐟💧💧🌊",
    "💧💧💧💧",
    "💧🏝️💧💧",
    "🌊💧💧💧",
    "💧💧🐟🌊",
]

# Grace period in seconds when user disconnects during enhanced-waterboard (they may rejoin)
ENHANCED_WATERBOARD_GRACE_SECONDS = 10

# Delay between major phases to avoid rate limits and allow "graceful" operation
PHASE_DELAY_SECONDS = 1.0


class WaterboardCog3(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DATABASE_PATHS["waterboard"]
        self.cooldown_multiplier = 2
        self.waterboard_cost = 200

        # Rate limiting for voice moves
        self.voice_move_semaphore = Semaphore(3)

        self.active_waterboard_sessions = 0
        self.waterboard_sessions_lock = asyncio.Lock()

        self._tables_created = False

        self.cleanup_exempt_users.start()

    @staticmethod
    def s_print_static(text_to_print) -> str:
        if isinstance(text_to_print, str):
            return text_to_print.encode("ascii", "replace").decode("ascii")
        return str(text_to_print)

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS waterboarded_users (
                        user_id INTEGER PRIMARY KEY,
                        last_waterboarded_time REAL,
                        usage_count INTEGER DEFAULT 0,
                        total_waterboarded INTEGER DEFAULT 0,
                        total_coins_spent INTEGER DEFAULT 0
                    )
                """)
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS exempt_users (
                        user_id INTEGER PRIMARY KEY,
                        exempt_until REAL
                    )
                """)
                await conn.commit()

    async def get_last_waterboarded_time(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT last_waterboarded_time FROM waterboarded_users WHERE user_id = ?",
                    (user_id,),
                )
                result = await cursor.fetchone()
        return result[0] if result else None

    async def executive_pardon(self, user_to_pardon_id: int, duration_hours: int):
        """Grants an executive pardon to a user, exempting them from waterboarding."""
        exempt_until = time.time() + (duration_hours * 3600)
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "INSERT OR REPLACE INTO exempt_users (user_id, exempt_until) VALUES (?, ?)",
                    (user_to_pardon_id, exempt_until),
                )
                await conn.commit()

    def get_waterboard_channels(self, guild, count: int = 10):
        """Get voice channels from the waterboard category, sorted by position. Returns up to `count` channels."""
        category = nextcord.utils.get(guild.categories, id=waterboard_category_id)
        if not category:
            return []
        voice_channels = [
            ch
            for ch in category.channels
            if isinstance(ch, nextcord.VoiceChannel)
        ]
        voice_channels.sort(key=lambda c: c.position)
        return voice_channels[:count]

    async def show_waterboard_category(self, guild):
        """Make the waterboard category visible to @everyone."""
        category = nextcord.utils.get(guild.categories, id=waterboard_category_id)
        if not category:
            return False
        try:
            await category.set_permissions(
                guild.default_role,
                view_channel=True,
                connect=True,
                reason="Waterboard session starting",
            )
            return True
        except Exception as e:
            self.cog_print(f"Error showing waterboard category: {WaterboardCog3.s_print_static(str(e))}")
            return False

    async def hide_waterboard_category(self, guild):
        """Hide the waterboard category from @everyone."""
        category = nextcord.utils.get(guild.categories, id=waterboard_category_id)
        if not category:
            return False
        try:
            await category.set_permissions(
                guild.default_role,
                view_channel=False,
                reason="Waterboard session ended",
            )
            return True
        except Exception as e:
            self.cog_print(f"Error hiding waterboard category: {WaterboardCog3.s_print_static(str(e))}")
            return False

    async def move_user_with_rate_limit(
        self, user: nextcord.Member, channel: nextcord.VoiceChannel, max_retries: int = 3
    ):
        """Move a user to a voice channel with rate limiting and exponential backoff."""
        async with self.voice_move_semaphore:
            for attempt in range(max_retries):
                try:
                    await user.move_to(channel)
                    await asyncio.sleep(0.3)
                    return True
                except nextcord.errors.HTTPException as e:
                    if e.status == 429:
                        wait_time = (2**attempt) * 0.5
                        self.cog_print(
                            f"Rate limited moving {self.s_print_static(user.name)}, waiting {wait_time}s (attempt {attempt + 1})"
                        )
                        await asyncio.sleep(wait_time)
                    elif e.status == 400:
                        self.cog_print(
                            f"User {self.s_print_static(user.name)} likely disconnected during move"
                        )
                        return False
                    else:
                        self.cog_print(
                            f"HTTP error moving {self.s_print_static(user.name)}: {e}"
                        )
                        return False
                except Exception as e:
                    self.cog_print(
                        f"Unexpected error moving {self.s_print_static(user.name)}: {e}"
                    )
                    return False

            self.cog_print(
                f"Failed to move {self.s_print_static(user.name)} after {max_retries} attempts"
            )
            return False

    async def move_users_in_batches(
        self, users: list, channel: nextcord.VoiceChannel, batch_size: int = 3
    ):
        """Move multiple users to a channel in batches. Returns list of successfully moved users."""
        successful_moves = []
        for i in range(0, len(users), batch_size):
            batch = users[i : i + batch_size]
            move_tasks = [
                self.move_user_with_rate_limit(user, channel) for user in batch
            ]
            try:
                results = await asyncio.gather(*move_tasks, return_exceptions=True)
                for user, result in zip(batch, results):
                    if isinstance(result, Exception):
                        self.cog_print(
                            f"Exception moving {self.s_print_static(user.name)}: {result}"
                        )
                    elif result is True:
                        successful_moves.append(user)
                        self.cog_print(
                            f"Successfully moved {self.s_print_static(user.name)} to {self.s_print_static(channel.name)}"
                        )
                    else:
                        self.cog_print(
                            f"Failed to move {self.s_print_static(user.name)} to {self.s_print_static(channel.name)}"
                        )
            except Exception as e:
                self.cog_print(f"Batch move error: {e}")
            if i + batch_size < len(users):
                await asyncio.sleep(0.8)
        return successful_moves

    # ---------- Admin prefix command: .create_water_channels ----------
    @commands.command(name="create_water_channels")
    async def create_water_channels(self, ctx, category_id: int = None):
        """
        [Admin only] Create 10 water-named voice channels.
        Usage: .create_water_channels [category_id]
        - No args: Creates a new "Waterboard" category and 10 channels in it. Returns the category ID for config.
        - With category_id: Creates 10 channels under the specified category.
        """
        if ctx.author.id not in admin_user_ids:
            await ctx.send("You do not have permission to use this command.")
            return

        guild = ctx.guild
        if not guild:
            await ctx.send("This command must be used in a server.")
            return

        if guild.id != GUILD_ID:
            await ctx.send("This command is not applicable in this guild.")
            return

        await ctx.send("Creating water channels... (this may take a moment)")

        try:
            if category_id:
                category = nextcord.utils.get(guild.categories, id=category_id)
                if not category:
                    await ctx.send(f"Category with ID `{category_id}` not found.")
                    return
                created_under = f"existing category `{category.name}` (ID: {category_id})"
            else:
                # Create new "Waterboard" category - hidden from @everyone by default
                category = await guild.create_category(
                    "Waterboard",
                    overwrites={
                        guild.default_role: nextcord.PermissionOverwrite(
                            view_channel=False
                        ),
                    },
                    reason="Waterboard3 setup - .create_water_channels",
                )
                created_under = f"new category `{category.name}` (ID: {category.id})"
                category_id = category.id

            # Create 10 voice channels with water names
            created_channels = []
            for name in WATER_CHANNEL_NAMES:
                ch = await guild.create_voice_channel(
                    name,
                    category=category,
                    reason="Waterboard3 setup - .create_water_channels",
                )
                created_channels.append(ch)
                await asyncio.sleep(0.5)  # Stagger creation to reduce rate limit risk

            if not category_id:
                category_id = category.id

            embed = nextcord.Embed(
                title="Water Channels Created",
                description=f"Created {len(created_channels)} voice channels under {created_under}.",
                color=nextcord.Color.green(),
            )
            embed.add_field(
                name="Config",
                value=f"Add to your env/Doppler: `WATERBOARD_CATEGORY_ID={category_id}`",
                inline=False,
            )
            embed.add_field(
                name="Channels",
                value=", ".join(ch.name for ch in created_channels),
                inline=False,
            )
            await ctx.send(embed=embed)
        except nextcord.errors.HTTPException as e:
            if e.status == 429:
                await ctx.send(
                    "Rate limited by Discord. Please wait a minute and try again."
                )
            else:
                await ctx.send(f"Discord API error: {e}")
        except Exception as e:
            await ctx.send(f"Error: {WaterboardCog3.s_print_static(str(e))}")

    # ---------- Slash commands ----------
    @nextcord.slash_command(
        name="executivepardon",
        description="[Admin] Grant exemption from waterboarding for a set time.",
        guild_ids=[GUILD_ID],
    )
    async def executivepardon_slash_command(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
        duration: int = nextcord.SlashOption(
            name="hours", description="Duration in hours", default=1, required=True
        ),
    ):
        if interaction.user.id not in admin_user_ids:
            embed = nextcord.Embed(
                title="Permission Denied",
                description="You do not have permission to use this command.",
                color=nextcord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await self.executive_pardon(user.id, duration)
        embed = nextcord.Embed(
            title="Executive Pardon",
            description=f"{user.mention} has been pardoned for {duration} hours.",
            color=nextcord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tasks.loop(minutes=10)
    async def cleanup_exempt_users(self):
        await self.bot.wait_until_ready()
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                current_time = time.time()
                await cursor.execute(
                    "DELETE FROM exempt_users WHERE exempt_until < ?", (current_time,)
                )
                await conn.commit()

    @cleanup_exempt_users.before_loop
    async def before_cleanup_exempt_users(self):
        await self.bot.wait_until_ready()
        if not self._tables_created:
            await self.create_tables()
            self._tables_created = True

    async def _common_waterboard_purchase_flow(
        self, interaction, user, is_enhanced=False, cost_multiplier=1.0
    ):
        """Shared DB + economy logic for waterboard and enhanced-waterboard. Returns (cost, next_cost_msg, error_embed) or (cost, next_cost, None)."""
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT exempt_until FROM exempt_users WHERE user_id = ?",
                    (user.id,),
                )
                exempt_result = await cursor.fetchone()
                if exempt_result and time.time() < exempt_result[0]:
                    exempt_until = exempt_result[0]
                    return (
                        None,
                        None,
                        nextcord.Embed(
                            title="Exempt User",
                            description=f"{user.mention} is exempt from waterboarding until <t:{int(exempt_until)}:F>.",
                            color=nextcord.Color.red(),
                        ),
                    )

                current_time = time.time()
                await cursor.execute(
                    "SELECT last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent FROM waterboarded_users WHERE user_id = ?",
                    (user.id,),
                )
                wb = await cursor.fetchone()
                current_usage = 0
                total_wb = 0
                total_coins = 0
                if wb:
                    last_time, current_usage, total_wb, total_coins = wb
                    if current_time - last_time > 1800:
                        current_usage = 0

                cost = int(
                    self.waterboard_cost
                    * cost_multiplier
                    * (self.cooldown_multiplier**current_usage)
                )

                economy_cog = self.bot.get_cog("Economy")
                if not economy_cog:
                    return (
                        None,
                        None,
                        nextcord.Embed(
                            title="Error",
                            description="Economy cog is not available.",
                            color=nextcord.Color.red(),
                        ),
                    )

                balance = await economy_cog.get_user_balance(interaction.user.id)
                if balance < cost:
                    return (
                        None,
                        None,
                        nextcord.Embed(
                            title="Insufficient Funds",
                            description=f"You need {cost} coins. Your balance is {balance} coins.",
                            color=nextcord.Color.orange(),
                        ),
                    )

                await economy_cog.deduct_user_balance(interaction.user.id, cost)
                new_usage = current_usage + 1
                next_cost = int(
                    self.waterboard_cost
                    * cost_multiplier
                    * (self.cooldown_multiplier**new_usage)
                )
                total_wb += 1
                total_coins += cost
                await cursor.execute(
                    "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
                    (user.id, current_time, new_usage, total_wb, total_coins),
                )
                await conn.commit()
                return (cost, next_cost, None)

    @nextcord.slash_command(
        name="waterboard", description="Waterboard a user (v3 - premade channels)", guild_ids=[GUILD_ID]
    )
    async def waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member):
        self.cog_print(f"User {interaction.user.id} used waterboard on {user.name}.")
        cost, next_cost, err = await self._common_waterboard_purchase_flow(
            interaction, user
        )
        if err:
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        embed_purchased = nextcord.Embed(
            title="Waterboard Purchased",
            description=f"You have successfully waterboarded {user.mention} for {cost} coins. Next usage: {next_cost} coins.",
            color=nextcord.Color.green(),
        )
        await interaction.response.send_message(embed=embed_purchased, ephemeral=True)

        if not user.voice or not user.voice.channel:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Waterboard Cancelled",
                    description=f"{user.mention} is not in a voice channel. You were still charged.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        if not waterboard_category_id:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Configuration Error",
                    description="WATERBOARD_CATEGORY_ID is not set. Run `.create_water_channels` first.",
                    color=nextcord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        asyncio.create_task(self.waterboard_user(interaction, user))

    @nextcord.slash_command(
        name="enhanced-waterboard",
        description="Enhanced waterboard that hides the original voice channel (v3)",
        guild_ids=[GUILD_ID],
    )
    async def enhanced_waterboard(
        self, interaction: nextcord.Interaction, user: nextcord.Member
    ):
        self.cog_print(f"User {interaction.user.id} used enhanced-waterboard on {user.name}.")
        cost, next_cost, err = await self._common_waterboard_purchase_flow(
            interaction, user, cost_multiplier=1.5
        )
        if err:
            await interaction.response.send_message(embed=err, ephemeral=True)
            return

        embed_purchased = nextcord.Embed(
            title="Enhanced Waterboard Purchased",
            description=f"You have successfully enhanced waterboarded {user.mention} for {cost} coins. Next usage: {next_cost} coins.",
            color=nextcord.Color.dark_blue(),
        )
        await interaction.response.send_message(embed=embed_purchased, ephemeral=True)

        if not user.voice or not user.voice.channel:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Enhanced Waterboard Cancelled",
                    description=f"{user.mention} is not in a voice channel. You were still charged.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        if not waterboard_category_id:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Configuration Error",
                    description="WATERBOARD_CATEGORY_ID is not set. Run `.create_water_channels` first.",
                    color=nextcord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        asyncio.create_task(self.enhanced_waterboard_user(interaction, user))

    @nextcord.slash_command(
        name="waterboard-party",
        description="Waterboard everyone in a voice channel (v3 - 2-channel relay)",
        guild_ids=[GUILD_ID],
    )
    async def waterboard_party(self, interaction: nextcord.Interaction):
        self.cog_print(f"User {interaction.user.id} used waterboard-party.")
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Not in Voice Channel",
                    description="You must be in a voice channel to use waterboard party.",
                    color=nextcord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        user_voice_channel = interaction.user.voice.channel
        target_users = [
            m
            for m in user_voice_channel.members
            if m.id != interaction.user.id and not m.bot
        ]
        if not target_users:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="No Targets",
                    description="No other users in your voice channel to waterboard.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        party_multiplier = 2.5
        base_cost = self.waterboard_cost
        total_cost = int(base_cost * party_multiplier * len(target_users))

        economy_cog = self.bot.get_cog("Economy")
        if not economy_cog:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Error",
                    description="Economy cog is not available.",
                    color=nextcord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        balance = await economy_cog.get_user_balance(interaction.user.id)
        if balance < total_cost:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Insufficient Funds",
                    description=f"You need {total_cost} coins. Your balance is {balance}.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        exempt_users = []
        final_targets = []
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                now = time.time()
                for u in target_users:
                    await cursor.execute(
                        "SELECT exempt_until FROM exempt_users WHERE user_id = ?",
                        (u.id,),
                    )
                    r = await cursor.fetchone()
                    if r and now < r[0]:
                        exempt_users.append(u)
                    else:
                        final_targets.append(u)

        if not final_targets:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="All Exempt",
                    description=f"All users are exempt: {', '.join(u.mention for u in exempt_users)}",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        final_cost = int(base_cost * party_multiplier * len(final_targets))
        await economy_cog.deduct_user_balance(interaction.user.id, final_cost)

        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                now = time.time()
                for u in final_targets:
                    await cursor.execute(
                        "SELECT total_waterboarded, total_coins_spent FROM waterboarded_users WHERE user_id = ?",
                        (u.id,),
                    )
                    r = await cursor.fetchone()
                    tw, tc = (r[0] + 1, r[1] + int(base_cost * party_multiplier)) if r else (1, int(base_cost * party_multiplier))
                    await cursor.execute(
                        "INSERT OR REPLACE INTO waterboarded_users (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) VALUES (?, ?, ?, ?, ?)",
                        (u.id, now, 0, tw, tc),
                    )
                await conn.commit()

        exempt_msg = f"\nExempt: {', '.join(u.mention for u in exempt_users)}" if exempt_users else ""
        await interaction.response.send_message(
            embed=nextcord.Embed(
                title="Waterboard Party Purchased",
                description=f"Waterboard party for {final_cost} coins! Targets: {', '.join(u.mention for u in final_targets)}{exempt_msg}",
                color=nextcord.Color.purple(),
            ),
            ephemeral=True,
        )

        if not waterboard_category_id:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Configuration Error",
                    description="WATERBOARD_CATEGORY_ID is not set. Run `.create_water_channels` first.",
                    color=nextcord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        asyncio.create_task(
            self.waterboard_party_users(
                interaction, final_targets, user_voice_channel
            )
        )

    @nextcord.slash_command(
        name="waterboard-ranks",
        description="All time waterboard rankings.",
        guild_ids=[GUILD_ID],
    )
    async def leaderboard(self, interaction: nextcord.Interaction):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, total_waterboarded, total_coins_spent FROM waterboarded_users ORDER BY total_waterboarded DESC LIMIT 10"
                )
                results = await cursor.fetchall()

        if not results:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Leaderboard",
                    description="No waterboard data available.",
                    color=nextcord.Color.blue(),
                ),
                ephemeral=True,
            )
            return

        embed = nextcord.Embed(
            title="Waterboard Leaderboard",
            description="Top 10 users who have been waterboarded the most.",
            color=nextcord.Color.gold(),
        )
        for rank, (uid, total_wb, total_coins) in enumerate(results, start=1):
            user = self.bot.get_user(uid)
            name = user.name if user else f"User ID: {uid}"
            embed.add_field(
                name=f"#{rank} - {name}",
                value=f"Waterboarded: {total_wb}\nCoins: {total_coins}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------- Core waterboard logic ----------
    async def waterboard_user(
        self, interaction: nextcord.Interaction, user: nextcord.Member
    ):
        guild = interaction.guild
        bot_spam = guild.get_channel(bot_spam_id)
        original_channel_id = user.voice.channel.id if user.voice else None
        session_counted = False

        try:
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True
            self.cog_print(f"Waterboard session started for {self.s_print_static(user.name)}. Active: {self.active_waterboard_sessions}")

            channels = self.get_waterboard_channels(guild, count=10)
            if len(channels) < 10:
                self.cog_print(
                    f"Waterboard category has only {len(channels)} channels. Need 10. Run .create_water_channels"
                )
                return

            await self.show_waterboard_category(guild)
            await asyncio.sleep(PHASE_DELAY_SECONDS)

            if not user.voice or not user.voice.channel:
                self.cog_print(f"{self.s_print_static(user.name)} left voice before waterboard.")
                return

            for ch in channels:
                if not user.voice or not user.voice.channel:
                    break
                success = await self.move_user_with_rate_limit(user, ch)
                if not success:
                    break
                await asyncio.sleep(1.0)

            await asyncio.sleep(PHASE_DELAY_SECONDS)

            if user.voice and original_channel_id:
                orig = self.bot.get_channel(original_channel_id)
                if orig:
                    await self.move_user_with_rate_limit(user, orig)

        except Exception as e:
            self.cog_print(f"Error waterboarding {self.s_print_static(user.name)}: {self.s_print_static(str(e))}")
        finally:
            if session_counted:
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    if self.active_waterboard_sessions == 0:
                        await self.hide_waterboard_category(guild)

            try:
                embed = nextcord.Embed(
                    description=f"{user.mention} was waterboarded by {interaction.user.mention}.",
                    color=nextcord.Color.blue(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                if bot_spam:
                    await bot_spam.send(
                        embed=nextcord.Embed(
                            description=f"{user.mention} was waterboarded by {interaction.user.mention}!",
                            color=nextcord.Color.blue(),
                        )
                    )
            except Exception:
                pass

    async def enhanced_waterboard_user(
        self, interaction: nextcord.Interaction, user: nextcord.Member
    ):
        guild = interaction.guild
        bot_spam = guild.get_channel(bot_spam_id)
        original_channel = user.voice.channel if user.voice else None
        original_permissions = (
            original_channel.overwrites_for(user) if original_channel else None
        )
        session_counted = False

        try:
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True
            self.cog_print(f"Enhanced waterboard started for {self.s_print_static(user.name)}")

            channels = self.get_waterboard_channels(guild, count=10)
            if len(channels) < 10:
                self.cog_print("Enhanced waterboard: need 10 channels in waterboard category.")
                return

            if original_channel:
                await original_channel.set_permissions(
                    user,
                    overwrite=nextcord.PermissionOverwrite(view_channel=False),
                    reason="Enhanced waterboard - hide channel",
                )

            await self.show_waterboard_category(guild)
            await asyncio.sleep(PHASE_DELAY_SECONDS)

            if not user.voice or not user.voice.channel:
                self.cog_print(f"{self.s_print_static(user.name)} left before enhanced waterboard.")
                return

            for ch in channels:
                if not user.voice or not user.voice.channel:
                    # Graceful wait: user may rejoin quickly
                    self.cog_print(
                        f"{self.s_print_static(user.name)} disconnected. Waiting {ENHANCED_WATERBOARD_GRACE_SECONDS}s to see if they rejoin..."
                    )
                    await asyncio.sleep(ENHANCED_WATERBOARD_GRACE_SECONDS)
                    if not user.voice or not user.voice.channel:
                        break
                success = await self.move_user_with_rate_limit(user, ch)
                if not success:
                    break
                await asyncio.sleep(1.0)

            await asyncio.sleep(PHASE_DELAY_SECONDS)

            if original_channel:
                await original_channel.set_permissions(
                    user,
                    overwrite=nextcord.PermissionOverwrite(view_channel=True, connect=True),
                    reason="Enhanced waterboard - restore access",
                )
                if user.voice:
                    await self.move_user_with_rate_limit(user, original_channel)

        except Exception as e:
            self.cog_print(
                f"Error enhanced waterboarding {self.s_print_static(user.name)}: {self.s_print_static(str(e))}"
            )
        finally:
            if original_channel:
                try:
                    if original_permissions:
                        await original_channel.set_permissions(
                            user, overwrite=original_permissions, reason="Restore perms"
                        )
                    else:
                        await original_channel.set_permissions(
                            user, overwrite=None, reason="Remove overwrite"
                        )
                except Exception:
                    pass

            if session_counted:
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    if self.active_waterboard_sessions == 0:
                        await self.hide_waterboard_category(guild)

            try:
                embed = nextcord.Embed(
                    description=f"{user.mention} was enhanced waterboarded by {interaction.user.mention}.",
                    color=nextcord.Color.dark_blue(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                if bot_spam:
                    await bot_spam.send(
                        embed=nextcord.Embed(
                            description=f"{user.mention} was enhanced waterboarded by {interaction.user.mention}! 💀",
                            color=nextcord.Color.dark_blue(),
                        )
                    )
            except Exception:
                pass

    async def waterboard_party_users(
        self,
        interaction: nextcord.Interaction,
        target_users: list,
        original_channel: nextcord.VoiceChannel,
    ):
        """Waterboard party: first two water channels only — all targets together, then relay, then home."""
        guild = interaction.guild
        bot_spam = guild.get_channel(bot_spam_id)
        original_channel_id = original_channel.id
        session_counted = False
        party_ids = {u.id for u in target_users}

        def party_members_in(channel: nextcord.VoiceChannel) -> list:
            return [m for m in channel.members if m.id in party_ids and not m.bot]

        try:
            async with self.waterboard_sessions_lock:
                self.active_waterboard_sessions += 1
                session_counted = True

            channels = self.get_waterboard_channels(guild, count=2)
            if len(channels) < 2:
                self.cog_print("Waterboard party needs at least 2 channels in waterboard category.")
                return

            ch_first, ch_second = channels[0], channels[1]

            await self.show_waterboard_category(guild)
            await asyncio.sleep(PHASE_DELAY_SECONDS)

            active = [u for u in target_users if u.voice and u.voice.channel]
            if not active:
                return

            # 1) Everyone still in voice → first water channel
            await self.move_users_in_batches(active, ch_first, batch_size=2)
            await asyncio.sleep(PHASE_DELAY_SECONDS)

            # 2) Everyone in first channel → second water channel
            in_first = party_members_in(ch_first)
            if in_first:
                await self.move_users_in_batches(in_first, ch_second, batch_size=2)
            await asyncio.sleep(PHASE_DELAY_SECONDS)

            # 3) Everyone still in either relay channel → original voice channel
            orig = self.bot.get_channel(original_channel_id)
            if orig:
                to_return = party_members_in(ch_first) + party_members_in(ch_second)
                if to_return:
                    await self.move_users_in_batches(to_return, orig, batch_size=2)

        except Exception as e:
            self.cog_print(f"Error waterboard party: {self.s_print_static(str(e))}")
        finally:
            if session_counted:
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    if self.active_waterboard_sessions == 0:
                        await self.hide_waterboard_category(guild)

            try:
                mentions = ", ".join(u.mention for u in target_users)
                embed = nextcord.Embed(
                    title="Waterboard Party Complete",
                    description=f"Waterboard party completed for: {mentions}",
                    color=nextcord.Color.purple(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                if bot_spam:
                    await bot_spam.send(
                        embed=nextcord.Embed(
                            description=f"🎉 **WATERBOARD PARTY!** 🎉\n{mentions} were waterboarded by {interaction.user.mention}! 💀💦",
                            color=nextcord.Color.purple(),
                        )
                    )
            except Exception:
                pass


async def setup(bot):
    cog = WaterboardCog3(bot)
    if not cog._tables_created:
        await cog.create_tables()
        cog._tables_created = True
    bot.add_cog(cog)
    boot_print("WaterboardCog_v3 has been added.")
