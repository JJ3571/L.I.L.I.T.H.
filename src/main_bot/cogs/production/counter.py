import nextcord
from nextcord.ext import commands
from nextcord import Interaction
import aiosqlite
import datetime
import logging
from typing import Optional, Dict, Any

from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.database_config import DATABASE_PATHS

DB_PATH = DATABASE_PATHS["counter"]

# Set up logging
logger = logging.getLogger(__name__)

class CounterError(Exception):
    """Base exception for Counter cog errors."""
    pass

class DatabaseError(CounterError):
    """Raised when database operations fail."""
    pass

class CounterNotFoundError(CounterError):
    """Raised when a counter is not found."""
    pass

class Counter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = DB_PATH

    async def cog_load(self):
        """Initialize the cog and create database tables."""
        try:
            await self.create_tables()
            logger.info("Counter cog initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Counter cog: {e}")
            raise

    async def create_tables(self):
        """Create necessary database tables if they don't exist."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS counters (
                        user_id INTEGER PRIMARY KEY,
                        current_count INTEGER NOT NULL DEFAULT 0,
                        last_updated TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        category TEXT DEFAULT 'default'
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS multi_counters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        counter_name TEXT NOT NULL,
                        option_labels TEXT NOT NULL,
                        option_counts TEXT NOT NULL,
                        last_updated TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(user_id, counter_name)
                    )
                """)
                await db.commit()
                logger.info("Counter tables created/verified successfully")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise DatabaseError(f"Failed to create tables: {e}")

    async def get_user_counter_data(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get counter data for a user."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT current_count, last_updated, category FROM counters WHERE user_id = ?",
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
            if row:
                return {
                    "count": row["current_count"],
                    "last_updated": datetime.datetime.fromisoformat(row["last_updated"]),
                    "category": row["category"]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get counter data for user {user_id}: {e}")
            raise DatabaseError(f"Failed to get counter data: {e}")

    async def update_user_counter(self, user_id: int, count: int, category: str = 'default'):
        """Update or create a user's counter."""
        try:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO counters (user_id, current_count, last_updated, created_at, category)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                    current_count = excluded.current_count,
                    last_updated = excluded.last_updated,
                    category = excluded.category
                """, (user_id, count, now_iso, now_iso, category))
                await db.commit()
            logger.info(f"Updated counter for user {user_id} to {count}")
        except Exception as e:
            logger.error(f"Failed to update counter for user {user_id}: {e}")
            raise DatabaseError(f"Failed to update counter: {e}")

    async def delete_user_counter(self, user_id: int):
        """Delete a user's counter."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT 1 FROM counters WHERE user_id = ?", (user_id,)) as cursor:
                    if not await cursor.fetchone():
                        raise CounterNotFoundError(f"No counter found for user {user_id}")
                await db.execute("DELETE FROM counters WHERE user_id = ?", (user_id,))
                await db.commit()
            logger.info(f"Deleted counter for user {user_id}")
        except CounterNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete counter for user {user_id}: {e}")
            raise DatabaseError(f"Failed to delete counter: {e}")

    async def get_multi_counter_data(self, user_id: int, counter_name: str) -> Optional[Dict[str, Any]]:
        """Get multi-counter data for a user."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT option_labels, option_counts, last_updated FROM multi_counters WHERE user_id = ? AND counter_name = ?",
                    (user_id, counter_name)
                ) as cursor:
                    row = await cursor.fetchone()
            if row:
                import json
                return {
                    "labels": json.loads(row["option_labels"]),
                    "counts": json.loads(row["option_counts"]),
                    "last_updated": datetime.datetime.fromisoformat(row["last_updated"])
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get multi-counter data for user {user_id}: {e}")
            raise DatabaseError(f"Failed to get multi-counter data: {e}")

    async def update_multi_counter(self, user_id: int, counter_name: str, labels: list, counts: list):
        """Update or create a user's multi-counter."""
        try:
            import json
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO multi_counters (user_id, counter_name, option_labels, option_counts, last_updated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, counter_name) DO UPDATE SET
                    option_labels = excluded.option_labels,
                    option_counts = excluded.option_counts,
                    last_updated = excluded.last_updated
                """, (user_id, counter_name, json.dumps(labels), json.dumps(counts), now_iso, now_iso))
                await db.commit()
            logger.info(f"Updated multi-counter for user {user_id}, counter: {counter_name}")
        except Exception as e:
            logger.error(f"Failed to update multi-counter for user {user_id}: {e}")
            raise DatabaseError(f"Failed to update multi-counter: {e}")

    async def delete_multi_counter(self, user_id: int, counter_name: str):
        """Delete a user's multi-counter."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT 1 FROM multi_counters WHERE user_id = ? AND counter_name = ?", (user_id, counter_name)) as cursor:
                    if not await cursor.fetchone():
                        raise CounterNotFoundError(f"No multi-counter found for user {user_id} with name {counter_name}")
                await db.execute("DELETE FROM multi_counters WHERE user_id = ? AND counter_name = ?", (user_id, counter_name))
                await db.commit()
            logger.info(f"Deleted multi-counter for user {user_id}, counter: {counter_name}")
        except CounterNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete multi-counter for user {user_id}: {e}")
            raise DatabaseError(f"Failed to delete multi-counter: {e}")

    def _create_embed(self, interaction: Interaction, count: int, category: str = 'default') -> nextcord.Embed:
        """Create an embed for the counter display."""
        embed = nextcord.Embed(
            title=f"Count: **{count}**",
            description=f"*Disappears after 24 hrs.*\nCategory: {category}",
            color=nextcord.Color.blue()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        return embed

    def _create_multi_embed(self, interaction: Interaction, counter_name: str, labels: list, counts: list) -> nextcord.Embed:
        """Create an embed for the multi-counter display."""
        embed = nextcord.Embed(
            title=f"Multi-Counter: **{counter_name}**",
            description="*Disappears after 24 hrs.*",
            color=nextcord.Color.green()
        )
        
        # Add a field for each counter option
        for i, (label, count) in enumerate(zip(labels, counts)):
            embed.add_field(
                name=f"{label}",
                value=f"**{count}**",
                inline=True
            )
        
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        return embed

    @nextcord.slash_command(
        name="counter",
        description="A personal counter.",
        guild_ids=[GUILD_ID]
    )
    async def counter_command(
        self,
        interaction: Interaction,
        category: str = nextcord.SlashOption(
            description="Category for your counter",
            required=False,
            default="default"
        )
    ):
        """Create or view your personal counter."""
        try:
            user_id = interaction.user.id
            await interaction.response.defer()

            counter_data = await self.get_user_counter_data(user_id)
            current_count = 0

            if not counter_data:
                await self.update_user_counter(user_id, 0, category)
                current_count = 0
            else:
                current_count = counter_data["count"]
                category = counter_data["category"]

            embed = self._create_embed(interaction, current_count, category)
            view = CounterView(owner_id=user_id, counter_cog=self)

            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message
            logger.info(f"Created counter for user {user_id} in category {category}")
        except Exception as e:
            logger.error(f"Error in counter command: {e}")
            await interaction.followup.send(
                "An error occurred while creating your counter. Please try again later.",
                ephemeral=True
            )

    @nextcord.slash_command(
        name="multicounter",
        description="Create a multi-option counter with 2-5 labeled options.",
        guild_ids=[GUILD_ID]
    )
    async def multicounter_command(
        self,
        interaction: Interaction,
        name: str = nextcord.SlashOption(
            description="Name for your multi-counter",
            required=True,
            max_length=32
        ),
        option1: str = nextcord.SlashOption(
            description="Label for first counter option",
            required=True,
            max_length=20
        ),
        option2: str = nextcord.SlashOption(
            description="Label for second counter option",
            required=True,
            max_length=20
        ),
        option3: str = nextcord.SlashOption(
            description="Label for third counter option",
            required=False,
            max_length=20
        ),
        option4: str = nextcord.SlashOption(
            description="Label for fourth counter option",
            required=False,
            max_length=20
        ),
        option5: str = nextcord.SlashOption(
            description="Label for fifth counter option",
            required=False,
            max_length=20
        )
    ):
        """Create or view your multi-option counter."""
        try:
            user_id = interaction.user.id
            await interaction.response.defer()

            # Build labels list, filtering out None values
            labels = [option1, option2]
            for option in [option3, option4, option5]:
                if option:
                    labels.append(option)

            # Validate number of options
            if len(labels) < 2 or len(labels) > 5:
                await interaction.followup.send(
                    "You must provide between 2 and 5 options for your multi-counter.",
                    ephemeral=True
                )
                return

            # Check if counter already exists
            counter_data = await self.get_multi_counter_data(user_id, name)
            
            if not counter_data:
                # Create new counter with all counts at 0
                counts = [0] * len(labels)
                await self.update_multi_counter(user_id, name, labels, counts)
            else:
                # Use existing data
                labels = counter_data["labels"]
                counts = counter_data["counts"]

            embed = self._create_multi_embed(interaction, name, labels, counts)
            view = MultiCounterView(owner_id=user_id, counter_name=name, labels=labels, counter_cog=self)

            message = await interaction.followup.send(embed=embed, view=view)
            view.message = message
            logger.info(f"Created multi-counter '{name}' for user {user_id} with {len(labels)} options")
        except Exception as e:
            logger.error(f"Error in multicounter command: {e}")
            await interaction.followup.send(
                "An error occurred while creating your multi-counter. Please try again later.",
                ephemeral=True
            )


# --- UI Views ---

class CounterView(nextcord.ui.View):
    def __init__(self, owner_id: int, counter_cog: 'Counter'):
        super().__init__(timeout=86400.0)  # 24 hours
        self.owner_id = owner_id
        self.message: nextcord.Message = None
        self.counter_cog = counter_cog
        # Whether others are allowed to increment this counter
        self.allow_others = False

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Check if the interaction is allowed.

        Owner always allowed. If `allow_others` is True, allow other users to
        perform the increment action only. Other actions (reset, settings)
        remain owner-only.
        """
        # Owner always allowed
        if interaction.user.id == self.owner_id:
            return True

        # Determine which component was used (safe access)
        custom_id = None
        try:
            custom_id = interaction.data.get('custom_id')
        except Exception:
            custom_id = None

        # If others are allowed, permit only the increment button
        if self.allow_others and custom_id == "increment_counter":
            return True

        # Otherwise deny
        await interaction.response.send_message(
            "This is not your counter!",
            ephemeral=True
        )
        return False

    async def _update_display(self, interaction: Interaction, new_count: int):
        """Update the counter display."""
        try:
            embed = self.message.embeds[0]
            embed.title = f"Count: **{new_count}**"
            
            if not interaction.response.is_done():
                await interaction.response.defer()
            await interaction.followup.edit_message(
                message_id=self.message.id,
                embed=embed
            )
        except Exception as e:
            logger.error(f"Error updating counter display: {e}")
            await interaction.followup.send(
                "Failed to update the counter display. Please try again.",
                ephemeral=True
            )

    @nextcord.ui.button(
        label="Increment",
        style=nextcord.ButtonStyle.green,
        custom_id="increment_counter"
    )
    async def increment_button(self, button: nextcord.ui.Button, interaction: Interaction):
        """Increment the counter."""
        try:
            counter_data = await self.counter_cog.get_user_counter_data(self.owner_id)
            new_count = (counter_data["count"] + 1) if counter_data else 1
            await self.counter_cog.update_user_counter(
                self.owner_id,
                new_count,
                counter_data["category"] if counter_data else "default"
            )
            await self._update_display(interaction, new_count)
        except Exception as e:
            logger.error(f"Error in increment button: {e}")
            await interaction.response.send_message(
                "Failed to increment counter. Please try again.",
                ephemeral=True
            )

    @nextcord.ui.button(
        label="Reset",
        style=nextcord.ButtonStyle.red,
        custom_id="reset_counter"
    )
    async def reset_button(self, button: nextcord.ui.Button, interaction: Interaction):
        """Reset the counter to zero."""
        try:
            counter_data = await self.counter_cog.get_user_counter_data(self.owner_id)
            await self.counter_cog.update_user_counter(
                self.owner_id,
                0,
                counter_data["category"] if counter_data else "default"
            )
            await self._update_display(interaction, 0)
        except Exception as e:
            logger.error(f"Error in reset button: {e}")
            await interaction.response.send_message(
                "Failed to reset counter. Please try again.",
                ephemeral=True
            )

    async def on_timeout(self):
        """Handle counter timeout."""
        try:
            # Disable all buttons
            for item in self.children:
                item.disabled = True

            # Stop the view from listening for interactions
            self.stop()
            
            # Delete the counter from the database
            await self.counter_cog.delete_user_counter(self.owner_id)

            # Update the message to show it has expired
            if self.message and self.message.embeds:
                embed = self.message.embeds[0]
                embed.description = "*This counter has expired.*"
                embed.color = nextcord.Color.greyple()
                try:
                    await self.message.edit(embed=embed, view=self)
                except nextcord.NotFound:
                    logger.info(f"Message for counter {self.owner_id} was deleted")
                except Exception as e:
                    logger.error(f"Error editing message on timeout: {e}")
        except Exception as e:
            logger.error(f"Error in counter timeout: {e}")


class MultiCounterView(nextcord.ui.View):
    def __init__(self, owner_id: int, counter_name: str, labels: list, counter_cog: 'Counter'):
        super().__init__(timeout=86400.0)  # 24 hours
        self.owner_id = owner_id
        self.counter_name = counter_name
        self.labels = labels
        self.message: nextcord.Message = None
        self.counter_cog = counter_cog
        self.decrement_mode = False
        # Whether others are allowed to use the option buttons
        self.allow_others = False
        
        # Add counter buttons dynamically
        self._add_counter_buttons()
        
        # Add settings button
        settings_button = nextcord.ui.Button(
            label="⚙️",
            style=nextcord.ButtonStyle.secondary,
            custom_id="settings",
            row=1
        )
        settings_button.callback = self.settings_callback
        self.add_item(settings_button)
        # Add allow-others toggle button (owner-only control)
        allow_button = nextcord.ui.Button(
            label="🔒 Owner Only",
            style=nextcord.ButtonStyle.secondary,
            custom_id="allow_others",
            row=1
        )
        allow_button.callback = self.allow_others_callback
        self.add_item(allow_button)

    def _add_counter_buttons(self):
        """Add buttons for each counter option."""
        # Clear existing counter buttons (keep settings button)
        items_to_remove = [item for item in self.children if hasattr(item, 'custom_id') and item.custom_id.startswith('counter_')]
        for item in items_to_remove:
            self.remove_item(item)
        
        # Add buttons for each label
        for i, label in enumerate(self.labels):
            button = nextcord.ui.Button(
                label=label,
                style=nextcord.ButtonStyle.red if self.decrement_mode else nextcord.ButtonStyle.green,
                custom_id=f"counter_{i}",
                row=0 if i < 3 else 1  # First 3 buttons on row 0, rest on row 1
            )
            button.callback = self._create_counter_callback(i)
            self.add_item(button)
        
        # Add reset button if in decrement mode
        if self.decrement_mode:
            reset_button = nextcord.ui.Button(
                label="Reset All",
                style=nextcord.ButtonStyle.danger,
                custom_id="reset_all",
                row=2
            )
            reset_button.callback = self.reset_all_callback
            self.add_item(reset_button)
        else:
            # Remove reset button if exists
            reset_item = next((item for item in self.children if hasattr(item, 'custom_id') and item.custom_id == 'reset_all'), None)
            if reset_item:
                self.remove_item(reset_item)

    def _create_counter_callback(self, index: int):
        """Create a callback function for a specific counter button."""
        async def callback(interaction: Interaction):
            try:
                counter_data = await self.counter_cog.get_multi_counter_data(self.owner_id, self.counter_name)
                if not counter_data:
                    await interaction.response.send_message(
                        "Counter data not found. Please try again.",
                        ephemeral=True
                    )
                    return
                
                counts = counter_data["counts"][:]
                if self.decrement_mode:
                    counts[index] = max(0, counts[index] - 1)  # Don't go below 0
                else:
                    counts[index] += 1
                
                await self.counter_cog.update_multi_counter(
                    self.owner_id,
                    self.counter_name,
                    self.labels,
                    counts
                )
                await self._update_display(interaction, counts)
            except Exception as e:
                logger.error(f"Error in counter button {index}: {e}")
                await interaction.response.send_message(
                    "Failed to update counter. Please try again.",
                    ephemeral=True
                )
        return callback

    async def settings_callback(self, interaction: Interaction):
        """Toggle between increment and decrement mode."""
        try:
            # Only owner can change settings
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message(
                    "Only the counter owner can change settings.",
                    ephemeral=True
                )
                return
            self.decrement_mode = not self.decrement_mode
            self._add_counter_buttons()  # Recreate buttons with new style
            
            await interaction.response.defer()
            await interaction.followup.edit_message(
                message_id=self.message.id,
                view=self
            )
        except Exception as e:
            logger.error(f"Error in settings callback: {e}")
            await interaction.response.send_message(
                "Failed to toggle settings. Please try again.",
                ephemeral=True
            )

    async def reset_all_callback(self, interaction: Interaction):
        """Reset all counters to zero."""
        try:
            # Only owner may reset all
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message(
                    "Only the counter owner can reset all counters.",
                    ephemeral=True
                )
                return
            counts = [0] * len(self.labels)
            await self.counter_cog.update_multi_counter(
                self.owner_id,
                self.counter_name,
                self.labels,
                counts
            )
            await self._update_display(interaction, counts)
        except Exception as e:
            logger.error(f"Error in reset all callback: {e}")
            await interaction.response.send_message(
                "Failed to reset counters. Please try again.",
                ephemeral=True
            )

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Check if the interaction is allowed.

        Owner always allowed. If `allow_others` is True, allow other users to
        press the option buttons (custom_id starting with 'counter_'). Other
        actions (settings, reset_all) remain owner-only.
        """
        # Owner always allowed
        if interaction.user.id == self.owner_id:
            return True

        # Determine which component was used
        custom_id = None
        try:
            custom_id = interaction.data.get('custom_id')
        except Exception:
            custom_id = None

        # If others are allowed, permit only option buttons
        if self.allow_others and custom_id and custom_id.startswith('counter_'):
            return True

        await interaction.response.send_message(
            "This is not your counter!",
            ephemeral=True
        )
        return False

    async def allow_others_callback(self, interaction: Interaction):
        """Toggle whether others can use the option buttons.

        Only the owner may toggle this. The button's label/style is updated
        to reflect the current state.
        """
        try:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message(
                    "Only the counter owner can change this setting.",
                    ephemeral=True
                )
                return

            self.allow_others = not self.allow_others
            # Update button label/style to reflect state
            allow_item = next((it for it in self.children if hasattr(it, 'custom_id') and it.custom_id == 'allow_others'), None)
            if allow_item:
                if self.allow_others:
                    allow_item.label = "🔓 Allow Others"
                    allow_item.style = nextcord.ButtonStyle.success
                else:
                    allow_item.label = "🔒 Owner Only"
                    allow_item.style = nextcord.ButtonStyle.secondary

            await interaction.response.defer()
            await interaction.followup.edit_message(
                message_id=self.message.id,
                view=self
            )
        except Exception as e:
            logger.error(f"Error toggling allow_others: {e}")
            await interaction.response.send_message(
                "Failed to change setting. Please try again.",
                ephemeral=True
            )

    async def _update_display(self, interaction: Interaction, new_counts: list):
        """Update the multi-counter display."""
        try:
            embed = self.counter_cog._create_multi_embed(interaction, self.counter_name, self.labels, new_counts)
            
            if not interaction.response.is_done():
                await interaction.response.defer()
            await interaction.followup.edit_message(
                message_id=self.message.id,
                embed=embed
            )
        except Exception as e:
            logger.error(f"Error updating multi-counter display: {e}")
            await interaction.followup.send(
                "Failed to update the counter display. Please try again.",
                ephemeral=True
            )

    async def on_timeout(self):
        """Handle multi-counter timeout."""
        try:
            # Disable all buttons
            for item in self.children:
                item.disabled = True

            # Stop the view from listening for interactions
            self.stop()
            
            # Delete the multi-counter from the database
            await self.counter_cog.delete_multi_counter(self.owner_id, self.counter_name)

            # Update the message to show it has expired
            if self.message and self.message.embeds:
                embed = self.message.embeds[0]
                embed.description = "*This multi-counter has expired.*"
                embed.color = nextcord.Color.greyple()
                try:
                    await self.message.edit(embed=embed, view=self)
                except nextcord.NotFound:
                    logger.info(f"Message for multi-counter {self.counter_name} for user {self.owner_id} was deleted")
                except Exception as e:
                    logger.error(f"Error editing message on timeout: {e}")
        except Exception as e:
            logger.error(f"Error in multi-counter timeout: {e}")

# Setup function for the cog
async def setup(bot):
    """Set up the Counter cog."""
    try:
        cog = Counter(bot)
        await cog.cog_load()
        bot.add_cog(cog)
        logger.info("Counter cog loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load Counter cog: {e}")
        raise