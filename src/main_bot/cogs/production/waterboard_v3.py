"""
What changed with v3: Rate-limit-friendly implementation using a prepopulated Waterboard category.
- No channel creation/deletion - category is hidden/shown instead
- /waterboard, /enhanced-waterboard, /waterboard-party use premade channels
- /waterboard-party uses the first 2 water channels only: everyone → channel 1 → channel 2 → back to origin
"""
import nextcord
from nextcord.ext import commands, tasks
import asyncio
import random
import time
from asyncio import Semaphore

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.guild_settings import config_missing_message, get_settings, is_bot_admin
from main_bot.server_configs.config import GUILD_ID
from main_bot.cogs.production.economy import Economy
from main_bot.cogs.production.shop import REPEL_WATER_CHALLENGE_DURATION_SECONDS

_WB = "waterboard"

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

# Seconds after a paid /waterboard returns the victim to their channel.
RETALIATE_WINDOW_SECONDS = 60

# How long the /retaliate quicktime stays open.
# Repel Water uses REPEL_WATER_CHALLENGE_DURATION_SECONDS in shop.py.
CHALLENGE_TIMEOUT_SECONDS = 8

# Inclusive range for the two-step math challenge operands.
CHALLENGE_TERM_MIN = 2
CHALLENGE_TERM_MAX = 12


def generate_water_challenge(
    rng: random.Random | None = None,
) -> tuple[str, int, list[int]]:
    """Return ``(prompt, correct, four shuffled choices)`` for the quicktime."""
    rng = rng or random.Random()
    low = min(CHALLENGE_TERM_MIN, CHALLENGE_TERM_MAX)
    high = max(CHALLENGE_TERM_MIN, CHALLENGE_TERM_MAX)
    a = rng.randint(low, high)
    b = rng.randint(low, high)
    c = rng.randint(low, high)
    kind = rng.choice(("add_mul", "mul_add", "sub_mul", "mul_sub", "div_add"))

    if kind == "add_mul":
        correct = (a + b) * c
        prompt = f"({a} + {b}) × {c}"
        wrongs = [a + b * c, (a + b) + c, a * b + c]
    elif kind == "mul_add":
        correct = a * b + c
        prompt = f"{a} × {b} + {c}"
        wrongs = [a * (b + c), (a + b) * c, a * b * c]
    elif kind == "sub_mul":
        if a < b:
            a, b = b, a
        elif a == b:
            a = b + 1
        correct = (a - b) * c
        prompt = f"({a} - {b}) × {c}"
        wrongs = [a - b * c, (a - b) + c, a * c - b]
    elif kind == "mul_sub":
        if c >= a * b:
            c = 1
        correct = a * b - c
        prompt = f"{a} × {b} - {c}"
        wrongs = [(a - b) * c, a * b + c, a * (b - c) if b > c else a * b - c - 2]
    else:
        divisor = rng.randint(low, high)
        quotient = rng.randint(low, high)
        dividend = divisor * quotient
        correct = quotient + c
        prompt = f"{dividend} ÷ {divisor} + {c}"
        wrongs = [quotient * c, quotient - c, (dividend + c) // divisor]

    unique_wrongs: list[int] = []
    for candidate in list(wrongs) + [correct + 1, correct - 1, correct + 2, correct - 2, correct + 10]:
        if candidate == correct or candidate in unique_wrongs:
            continue
        unique_wrongs.append(candidate)
        if len(unique_wrongs) == 3:
            break
    options = unique_wrongs[:3] + [correct]
    rng.shuffle(options)
    return prompt, correct, options


class WaterQuicktimeButton(nextcord.ui.Button):
    def __init__(self, answer: int, index: int):
        super().__init__(
            label=str(answer),
            style=nextcord.ButtonStyle.primary,
            custom_id=f"water_quicktime_{index}",
        )
        self.answer = answer

    async def callback(self, interaction: nextcord.Interaction):
        view = self.view
        if interaction.user.id != view.challenger_id:
            await interaction.response.send_message("This challenge is not yours.", ephemeral=True)
            return
        if view.resolved or time.monotonic() > view.expires_at:
            if not view.resolved:
                view.resolve(False)
            if not interaction.response.is_done():
                await interaction.response.send_message("Too late.", ephemeral=True)
            return

        success = self.answer == view.correct
        view.resolve(success)
        title = "Correct" if success else "Wrong"
        color = nextcord.Color.green() if success else nextcord.Color.red()
        embed = nextcord.Embed(
            title=title,
            description=f"**{view.prompt}** = {view.correct}",
            color=color,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class WaterQuicktimeView(nextcord.ui.View):
    def __init__(
        self,
        *,
        challenger_id: int,
        prompt: str,
        correct: int,
        options: list[int],
        future: asyncio.Future,
        interaction: nextcord.Interaction,
        timeout_seconds: float = CHALLENGE_TIMEOUT_SECONDS,
    ):
        super().__init__(timeout=timeout_seconds)
        self.challenger_id = challenger_id
        self.prompt = prompt
        self.correct = correct
        self.future = future
        self.interaction = interaction
        self.challenge_message = None
        self.timeout_seconds = timeout_seconds
        self.expires_at = time.monotonic() + timeout_seconds
        self.resolved = False
        for index, answer in enumerate(options):
            self.add_item(WaterQuicktimeButton(answer, index))

    def resolve(self, success: bool) -> None:
        if self.resolved:
            return
        self.resolved = True
        for child in self.children:
            child.disabled = True
        self.stop()
        if not self.future.done():
            self.future.set_result(success)

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolve(False)
        embed = nextcord.Embed(
            title="Too slow",
            description=f"**{self.prompt}** = {self.correct}",
            color=nextcord.Color.red(),
        )
        try:
            if self.challenge_message is not None:
                await self.challenge_message.edit(embed=embed, view=self)
            else:
                await self.interaction.edit_original_response(embed=embed, view=self)
        except Exception:
            pass


class WaterboardCog3(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        self.cooldown_multiplier = 2
        self.waterboard_cost = 200

        # Rate limiting for voice moves
        self.voice_move_semaphore = Semaphore(3)

        self.active_waterboard_sessions = 0
        self.waterboard_sessions_lock = asyncio.Lock()

        # victim_id -> {"attacker_id": int, "expires_at": float}
        # In memory: the window is RETALIATE_WINDOW_SECONDS, so a restart only drops a token about to expire.
        self.retaliate_tokens: dict[int, dict] = {}
        # victim_id -> attacker_id while a paid waterboard is still moving them.
        self.retaliate_pending: dict[int, int] = {}
        # victim_id -> /retaliate interaction typed before they landed back home.
        self.queued_retaliates: dict[int, nextcord.Interaction] = {}

        self._tables_created = False

        self.cleanup_exempt_users.start()

    @staticmethod
    def s_print_static(text_to_print) -> str:
        if isinstance(text_to_print, str):
            return text_to_print.encode("ascii", "replace").decode("ascii")
        return str(text_to_print)

    async def create_tables(self):
        return

    async def get_last_waterboarded_time(self, user_id):
        async with self.bot.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'SELECT last_waterboarded_time FROM "{_WB}".waterboarded_users WHERE user_id = $1',
                user_id,
            )
            return row["last_waterboarded_time"] if row else None

    async def executive_pardon(self, user_to_pardon_id: int, duration_hours: int):
        """Grants an executive pardon to a user, exempting them from waterboarding."""
        exempt_until = time.time() + (duration_hours * 3600)
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(
                f'INSERT INTO "{_WB}".exempt_users (user_id, exempt_until) VALUES ($1, $2) '
                f'ON CONFLICT (user_id) DO UPDATE SET exempt_until = EXCLUDED.exempt_until',
                user_to_pardon_id,
                exempt_until,
            )

    async def clear_executive_pardon(self, user_id: int) -> None:
        """Remove a pardon exemption before its timer ends."""
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(
                f'DELETE FROM "{_WB}".exempt_users WHERE user_id = $1',
                user_id,
            )

    async def get_active_exemption(self, user_id: int) -> float | None:
        """Return the exemption timestamp when the user is currently pardoned."""
        async with self.bot.pg_pool.acquire() as conn:
            exempt_until = await conn.fetchval(
                f'SELECT exempt_until FROM "{_WB}".exempt_users WHERE user_id = $1',
                user_id,
            )
        if exempt_until is not None and time.time() < exempt_until:
            return float(exempt_until)
        return None

    def _exemption_embed(self, user: nextcord.Member, exempt_until: float) -> nextcord.Embed:
        return nextcord.Embed(
            title="Exempt User",
            description=f"{user.mention} is exempt from waterboarding until <t:{int(exempt_until)}:F>.",
            color=nextcord.Color.red(),
        )

    def _waterboard_config_embed(self) -> nextcord.Embed | None:
        gs = get_settings()
        if gs.is_group_skipped("waterboard") or not gs.get_int("waterboard_category_id"):
            return nextcord.Embed(
                title="Configuration Error",
                description=config_missing_message(
                    "waterboard", skipped=gs.is_group_skipped("waterboard")
                ),
                color=nextcord.Color.red(),
            )
        return None

    async def target_has_active_repel(self, user_id: int) -> bool:
        """True when Repel Water is running. Callers must not reveal the timer."""
        cog = self.bot.get_cog("ShopCog")
        if cog is None:
            return False
        checker = getattr(cog, "is_repel_active", None)
        if not asyncio.iscoroutinefunction(checker):
            return False
        return bool(await checker(user_id))

    def grant_retaliate_token(self, victim_id: int, attacker_id: int) -> None:
        if victim_id == attacker_id:
            return
        self.retaliate_tokens[victim_id] = {
            "attacker_id": attacker_id,
            "expires_at": time.time() + RETALIATE_WINDOW_SECONDS,
        }
        self.cog_print(
            f"Retaliate token granted to {victim_id} against {attacker_id} "
            f"for {RETALIATE_WINDOW_SECONDS}s."
        )

    def retaliate_token_status(self, victim_id: int) -> str:
        """``ready``, ``expired``, or ``missing``. Expired tokens are dropped."""
        token = self.retaliate_tokens.get(victim_id)
        if token is None:
            return "missing"
        if time.time() >= token["expires_at"]:
            self.retaliate_tokens.pop(victim_id, None)
            return "expired"
        return "ready"

    def finish_retaliate_window(
        self, victim_id: int, attacker_id: int, *, landed: bool
    ) -> tuple[nextcord.Interaction | None, bool]:
        """Clear the in-progress mark. Returns ``(queued interaction, should_run)``."""
        self.retaliate_pending.pop(victim_id, None)
        queued = self.queued_retaliates.pop(victim_id, None)
        if landed:
            self.grant_retaliate_token(victim_id, attacker_id)
            return queued, True
        return queued, False

    def consume_retaliate_token(self, victim_id: int) -> int | None:
        token = self.retaliate_tokens.pop(victim_id, None)
        if token is None or time.time() >= token["expires_at"]:
            return None
        return int(token["attacker_id"])

    async def record_free_waterboard(self, user_id: int) -> None:
        """Count a free dunk on the leaderboard without moving the paid price ladder."""
        async with self.bot.pg_pool.acquire() as conn:
            await conn.execute(
                f'INSERT INTO "{_WB}".waterboarded_users '
                f'(user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) '
                f'VALUES ($1, 0, 0, 1, 0) '
                f'ON CONFLICT (user_id) DO UPDATE SET '
                f'total_waterboarded = "{_WB}".waterboarded_users.total_waterboarded + 1',
                user_id,
            )

    async def present_quicktime(
        self,
        interaction: nextcord.Interaction,
        challenger: nextcord.Member,
        *,
        title: str,
        intro: str,
        already_responded: bool = False,
        timeout_seconds: float = CHALLENGE_TIMEOUT_SECONDS,
    ) -> bool:
        """Ephemeral four-button math challenge. True when they answer correctly in time."""
        prompt, correct, options = generate_water_challenge()
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        view = WaterQuicktimeView(
            challenger_id=challenger.id,
            prompt=prompt,
            correct=correct,
            options=options,
            future=future,
            interaction=interaction,
            timeout_seconds=timeout_seconds,
        )
        embed = nextcord.Embed(
            title=title,
            description=(
                f"{intro}\n\n**{prompt}**\n\nYou have {timeout_seconds} seconds."
            ),
            color=nextcord.Color.blue(),
        )
        if already_responded:
            view.challenge_message = await interaction.followup.send(
                embed=embed, view=view, ephemeral=True
            )
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.expires_at = time.monotonic() + timeout_seconds
        try:
            return bool(await asyncio.wait_for(future, timeout=timeout_seconds + 2))
        except asyncio.TimeoutError:
            return False

    async def _begin_paid_waterboard(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
        *,
        already_responded: bool,
    ) -> None:
        cost, next_cost, err = await self._common_waterboard_purchase_flow(interaction, user)
        send = interaction.followup.send if already_responded else interaction.response.send_message
        if err:
            await send(embed=err, ephemeral=True)
            return

        embed_purchased = nextcord.Embed(
            title="Waterboard Purchased",
            description=(
                f"You have successfully waterboarded {user.mention} for {cost} coins. "
                f"Next usage: {next_cost} coins."
            ),
            color=nextcord.Color.green(),
        )
        await send(embed=embed_purchased, ephemeral=True)

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

        config_embed = self._waterboard_config_embed()
        if config_embed is not None:
            await interaction.followup.send(embed=config_embed, ephemeral=True)
            return

        asyncio.create_task(
            self.waterboard_user(interaction, user, grant_retaliate=True)
        )

    async def _repel_then_waterboard(
        self, interaction: nextcord.Interaction, user: nextcord.Member
    ) -> None:
        """Attacker hit an active Repel Water. Challenge them before any coins move."""
        config_embed = self._waterboard_config_embed()
        if config_embed is not None:
            await interaction.response.send_message(embed=config_embed, ephemeral=True)
            return

        self.cog_print(
            f"Repel Water challenged {interaction.user.id} while targeting {user.id}."
        )
        success = await self.present_quicktime(
            interaction,
            interaction.user,
            title="The water pushes back",
            intro="Solve this, or you go in instead.",
            timeout_seconds=REPEL_WATER_CHALLENGE_DURATION_SECONDS,
        )
        if success:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    description="The water gives way.",
                    color=nextcord.Color.green(),
                ),
                ephemeral=True,
            )
            await self._begin_paid_waterboard(interaction, user, already_responded=True)
            return

        attacker = interaction.user
        if not attacker.voice or not attacker.voice.channel:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="The water finds no one",
                    description=(
                        "You missed, and you are not in a voice channel. "
                        "Nobody goes in, and you were not charged."
                    ),
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        await self.record_free_waterboard(attacker.id)
        public = f"The water turns around! {attacker.mention} is swept away."
        asyncio.create_task(
            self.waterboard_user(
                interaction,
                attacker,
                caused_by=user,
                grant_retaliate=False,
                public_description=public,
                ephemeral_description="The water turns around. You're going in.",
            )
        )

    def get_waterboard_channels(self, guild, count: int = 10):
        """Get voice channels from the waterboard category, sorted by position. Returns up to `count` channels."""
        category = nextcord.utils.get(guild.categories, id=get_settings().get_int("waterboard_category_id"))
        if not category:
            return []
        voice_channels = [
            ch
            for ch in category.channels
            if getattr(ch, "type", None) == nextcord.ChannelType.voice
        ]
        voice_channels.sort(key=lambda c: c.position)
        return voice_channels[:count]

    async def show_waterboard_category(self, guild):
        """Make the waterboard category visible to @everyone."""
        category = nextcord.utils.get(guild.categories, id=get_settings().get_int("waterboard_category_id"))
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
        category = nextcord.utils.get(guild.categories, id=get_settings().get_int("waterboard_category_id"))
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
        if not isinstance(ctx.author, nextcord.Member) or not is_bot_admin(ctx.author):
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
        if not isinstance(interaction.user, nextcord.Member) or not is_bot_admin(interaction.user):
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
        async with self.bot.pg_pool.acquire() as conn:
            current_time = time.time()
            await conn.execute(
                f'DELETE FROM "{_WB}".exempt_users WHERE exempt_until < $1', current_time
            )

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
        async with self.bot.pg_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f'SELECT exempt_until FROM "{_WB}".exempt_users WHERE user_id = $1',
                    user.id,
                )
                exempt_result = (row["exempt_until"],) if row else None
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
                wb = await conn.fetchrow(
                    f'SELECT last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent '
                    f'FROM "{_WB}".waterboarded_users WHERE user_id = $1',
                    user.id,
                )
                current_usage = 0
                total_wb = 0
                total_coins = 0
                if wb:
                    last_time = wb["last_waterboarded_time"]
                    current_usage = wb["usage_count"]
                    total_wb = wb["total_waterboarded"]
                    total_coins = wb["total_coins_spent"]
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
                await conn.execute(
                    f'INSERT INTO "{_WB}".waterboarded_users '
                    f'(user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) '
                    f'VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id) DO UPDATE SET '
                    f'last_waterboarded_time = EXCLUDED.last_waterboarded_time, '
                    f'usage_count = EXCLUDED.usage_count, '
                    f'total_waterboarded = EXCLUDED.total_waterboarded, '
                    f'total_coins_spent = EXCLUDED.total_coins_spent',
                    user.id,
                    current_time,
                    new_usage,
                    total_wb,
                    total_coins,
                )
                return (cost, next_cost, None)

    @nextcord.slash_command(
        name="waterboard", description="Waterboard a user", guild_ids=[GUILD_ID]
    )
    async def waterboard(self, interaction: nextcord.Interaction, user: nextcord.Member):
        self.cog_print(f"User {interaction.user.id} used waterboard on {user.name}.")
        exempt_until = await self.get_active_exemption(user.id)
        if exempt_until is not None:
            await interaction.response.send_message(
                embed=self._exemption_embed(user, exempt_until), ephemeral=True
            )
            return

        if (
            user.voice
            and user.voice.channel
            and await self.target_has_active_repel(user.id)
        ):
            await self._repel_then_waterboard(interaction, user)
            return

        await self._begin_paid_waterboard(interaction, user, already_responded=False)

    @nextcord.slash_command(
        name="retaliate",
        description="After a waterboard, solve a quicktime event and submerge your attacker for free!",
        guild_ids=[GUILD_ID],
    )
    async def retaliate(self, interaction: nextcord.Interaction):
        self.cog_print(f"User {interaction.user.id} used retaliate.")
        status = self.retaliate_token_status(interaction.user.id)
        if status == "missing":
            if interaction.user.id in self.retaliate_pending:
                await self._queue_retaliate(interaction)
                return
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Nothing to retaliate against...",
                    description="You have not been waterboarded recently.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return
        if status == "expired":
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Too slow",
                    description="The moment to retaliate has passed.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        await self._continue_retaliate(interaction, already_responded=False)

    async def _queue_retaliate(self, interaction: nextcord.Interaction) -> None:
        """Hold /retaliate until the paid waterboard returns them home."""
        if interaction.user.id in self.queued_retaliates:
            await interaction.response.send_message(
                embed=nextcord.Embed(
                    title="Already queued",
                    description="Your retaliate is already waiting until you're back in your voice channel.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return
        self.queued_retaliates[interaction.user.id] = interaction
        await interaction.response.send_message(
            embed=nextcord.Embed(
                title="Still in the water",
                description=(
                    "You're still going through the water. "
                    f"The {RETALIATE_WINDOW_SECONDS}-second retaliation clock starts once you're "
                    "back in your voice channel. This retaliate is queued and will begin then."
                ),
                color=nextcord.Color.blue(),
            ),
            ephemeral=True,
        )

    async def _drop_queued_retaliate(self, interaction: nextcord.Interaction) -> None:
        try:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Retaliate cancelled",
                    description="The waterboard ended before you got back, so the retaliate did not start.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
        except Exception as e:
            self.cog_print(f"Could not cancel a queued retaliate: {self.s_print_static(str(e))}")

    async def _run_queued_retaliate(self, interaction: nextcord.Interaction) -> None:
        try:
            await self._continue_retaliate(interaction, already_responded=True)
        except Exception as e:
            self.cog_print(f"Queued retaliate failed: {self.s_print_static(str(e))}")

    async def _continue_retaliate(
        self, interaction: nextcord.Interaction, *, already_responded: bool
    ) -> None:
        send = interaction.followup.send if already_responded else interaction.response.send_message
        if not interaction.user.voice or not interaction.user.voice.channel:
            await send(
                embed=nextcord.Embed(
                    title="Not in Voice Channel",
                    description="You need to be in a voice channel to retaliate.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        config_embed = self._waterboard_config_embed()
        if config_embed is not None:
            await send(embed=config_embed, ephemeral=True)
            return

        attacker_id = self.consume_retaliate_token(interaction.user.id)
        if attacker_id is None:
            await send(
                embed=nextcord.Embed(
                    title="Nothing to retaliate against",
                    description="You have not been waterboarded recently.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        attacker = interaction.guild.get_member(attacker_id) if interaction.guild else None
        if attacker is None:
            await send(
                embed=nextcord.Embed(
                    title="They're gone",
                    description="The person who waterboarded you is no longer in the server.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        exempt_until = await self.get_active_exemption(attacker.id)
        if exempt_until is not None:
            await send(embed=self._exemption_embed(attacker, exempt_until), ephemeral=True)
            return

        success = await self.present_quicktime(
            interaction,
            interaction.user,
            title="Retaliate",
            intro=f"Solve this to send {attacker.mention} in instead. Miss, and you go back in.",
            already_responded=already_responded,
        )
        if success:
            if not attacker.voice or not attacker.voice.channel:
                await interaction.followup.send(
                    embed=nextcord.Embed(
                        title="They got away",
                        description=f"{attacker.mention} is not in a voice channel.",
                        color=nextcord.Color.orange(),
                    ),
                    ephemeral=True,
                )
                return
            await self.record_free_waterboard(attacker.id)
            public = f"{interaction.user.mention} retaliates. {attacker.mention} is swept away."
            asyncio.create_task(
                self.waterboard_user(
                    interaction,
                    attacker,
                    caused_by=interaction.user,
                    grant_retaliate=False,
                    public_description=public,
                    ephemeral_description=public,
                )
            )
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="The water finds no one",
                    description="You missed, and you are not in a voice channel.",
                    color=nextcord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        await self.record_free_waterboard(interaction.user.id)
        public = f"{interaction.user.mention} fumbles the retaliation and goes back under."
        asyncio.create_task(
            self.waterboard_user(
                interaction,
                interaction.user,
                caused_by=interaction.user,
                grant_retaliate=False,
                public_description=public,
                ephemeral_description="You missed. Back in you go.",
            )
        )

    @nextcord.slash_command(
        name="enhanced-waterboard",
        description="Enhanced waterboard that hides the original voice channel... for a price.",
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

        gs = get_settings()
        if gs.is_group_skipped("waterboard") or not gs.get_int("waterboard_category_id"):
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Configuration Error",
                    description=config_missing_message(
                        "waterboard", skipped=gs.is_group_skipped("waterboard")
                    ),
                    color=nextcord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        asyncio.create_task(self.enhanced_waterboard_user(interaction, user))

    @nextcord.slash_command(
        name="waterboard-party",
        description="Air this b**** out!",
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
        async with self.bot.pg_pool.acquire() as conn:
            now = time.time()
            for u in target_users:
                r = await conn.fetchrow(
                    f'SELECT exempt_until FROM "{_WB}".exempt_users WHERE user_id = $1',
                    u.id,
                )
                if r and now < r["exempt_until"]:
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

        async with self.bot.pg_pool.acquire() as conn:
            async with conn.transaction():
                now = time.time()
                for u in final_targets:
                    r = await conn.fetchrow(
                        f'SELECT total_waterboarded, total_coins_spent FROM "{_WB}".waterboarded_users WHERE user_id = $1',
                        u.id,
                    )
                    if r:
                        tw = r["total_waterboarded"] + 1
                        tc = r["total_coins_spent"] + int(base_cost * party_multiplier)
                    else:
                        tw = 1
                        tc = int(base_cost * party_multiplier)
                    await conn.execute(
                        f'INSERT INTO "{_WB}".waterboarded_users '
                        f'(user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent) '
                        f'VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id) DO UPDATE SET '
                        f'last_waterboarded_time = EXCLUDED.last_waterboarded_time, '
                        f'usage_count = EXCLUDED.usage_count, '
                        f'total_waterboarded = EXCLUDED.total_waterboarded, '
                        f'total_coins_spent = EXCLUDED.total_coins_spent',
                        u.id,
                        now,
                        0,
                        tw,
                        tc,
                    )

        exempt_msg = f"\nExempt: {', '.join(u.mention for u in exempt_users)}" if exempt_users else ""
        await interaction.response.send_message(
            embed=nextcord.Embed(
                title="Waterboard Party Purchased",
                description=f"Waterboard party for {final_cost} coins! Targets: {', '.join(u.mention for u in final_targets)}{exempt_msg}",
                color=nextcord.Color.purple(),
            ),
            ephemeral=True,
        )

        gs = get_settings()
        if gs.is_group_skipped("waterboard") or not gs.get_int("waterboard_category_id"):
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Configuration Error",
                    description=config_missing_message(
                        "waterboard", skipped=gs.is_group_skipped("waterboard")
                    ),
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
        async with self.bot.pg_pool.acquire() as conn:
            results = await conn.fetch(
                f'SELECT user_id, total_waterboarded, total_coins_spent FROM "{_WB}".waterboarded_users '
                f'ORDER BY total_waterboarded DESC LIMIT 10'
            )

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
        for rank, row in enumerate(results, start=1):
            uid = row["user_id"]
            total_wb = row["total_waterboarded"]
            total_coins = row["total_coins_spent"]
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
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
        *,
        caused_by: nextcord.Member | None = None,
        grant_retaliate: bool = False,
        public_description: str | None = None,
        ephemeral_description: str | None = None,
    ):
        guild = interaction.guild
        bot_spam = guild.get_channel(get_settings().get_int("bot_spam_id"))
        caused_by = caused_by or interaction.user
        original_channel_id = user.voice.channel.id if user.voice else None
        session_counted = False
        landed_home = False
        tracking_retaliate = False

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

            if grant_retaliate:
                self.retaliate_pending[user.id] = caused_by.id
                tracking_retaliate = True

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
                    landed_home = await self.move_user_with_rate_limit(user, orig)

        except Exception as e:
            self.cog_print(f"Error waterboarding {self.s_print_static(user.name)}: {self.s_print_static(str(e))}")
        finally:
            queued_retaliate = None
            run_queued_retaliate = False
            if tracking_retaliate:
                queued_retaliate, run_queued_retaliate = self.finish_retaliate_window(
                    user.id, caused_by.id, landed=landed_home
                )

            if session_counted:
                async with self.waterboard_sessions_lock:
                    self.active_waterboard_sessions -= 1
                    if self.active_waterboard_sessions == 0:
                        await self.hide_waterboard_category(guild)

            try:
                public = public_description or (
                    f"{user.mention} was waterboarded by {caused_by.mention}!"
                )
                ephemeral = ephemeral_description or (
                    f"{user.mention} was waterboarded by {caused_by.mention}."
                )
                await interaction.followup.send(
                    embed=nextcord.Embed(description=ephemeral, color=nextcord.Color.blue()),
                    ephemeral=True,
                )
                if bot_spam:
                    await bot_spam.send(
                        embed=nextcord.Embed(description=public, color=nextcord.Color.blue())
                    )
            except Exception:
                pass

            if queued_retaliate is not None:
                if run_queued_retaliate:
                    asyncio.create_task(self._run_queued_retaliate(queued_retaliate))
                else:
                    asyncio.create_task(self._drop_queued_retaliate(queued_retaliate))

    async def enhanced_waterboard_user(
        self, interaction: nextcord.Interaction, user: nextcord.Member
    ):
        guild = interaction.guild
        bot_spam = guild.get_channel(get_settings().get_int("bot_spam_id"))
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
        bot_spam = guild.get_channel(get_settings().get_int("bot_spam_id"))
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
