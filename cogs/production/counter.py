import nextcord
from nextcord.ext import commands
from nextcord import Interaction
import aiosqlite
import datetime
import logging
from typing import Optional, Dict, Any

from server_configs.config import GUILD_ID
DB_PATH = "counter.db"

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

    def _create_embed(self, interaction: Interaction, count: int, category: str = 'default') -> nextcord.Embed:
        """Create an embed for the counter display."""
        embed = nextcord.Embed(
            title=f"Count: **{count}**",
            description=f"*Disappears after 24 hrs.*\nCategory: {category}",
            color=nextcord.Color.blue()
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


# --- UI Views ---

class CounterView(nextcord.ui.View):
    def __init__(self, owner_id: int, counter_cog: 'Counter'):
        super().__init__(timeout=86400.0)  # 24 hours
        self.owner_id = owner_id
        self.message: nextcord.Message = None
        self.counter_cog = counter_cog

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Check if the interaction is from the counter owner."""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This is not your counter!",
                ephemeral=True
            )
            return False
        return True

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