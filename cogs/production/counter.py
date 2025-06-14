import nextcord
from nextcord.ext import commands
from nextcord import Interaction
import aiosqlite
import datetime
import asyncio

# Assuming GUILD_ID is defined in a config file like so:
from server_configs.config import GUILD_ID


class Counter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "counter.db"

    async def create_tables(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS counters (
                    user_id INTEGER PRIMARY KEY,
                    current_count INTEGER NOT NULL DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            """)
            await db.commit()

    async def get_user_counter_data(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT current_count, last_updated FROM counters WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
        if row:
            return {"count": row[0], "last_updated": datetime.datetime.fromisoformat(row[1])}
        return None

    async def update_user_counter(self, user_id: int, count: int):
        async with aiosqlite.connect(self.db_path) as db:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            await db.execute("""
                INSERT INTO counters (user_id, current_count, last_updated)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                current_count = excluded.current_count,
                last_updated = excluded.last_updated
            """, (user_id, count, now_iso))
            await db.commit()

    async def delete_user_counter(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            # Check if the counter exists before deleting
            async with db.execute("SELECT 1 FROM counters WHERE user_id = ?", (user_id,)) as cursor:
                if await cursor.fetchone():
                    await db.execute("DELETE FROM counters WHERE user_id = ?", (user_id,))
                    await db.commit()
                    print(f"Deleted counter for user {user_id} from DB.")

    def _create_embed(self, interaction: Interaction, count: int) -> nextcord.Embed:
        embed = nextcord.Embed(
            title=f"Count: **{count}**",
            description="*Disappears after 24 hrs.*",
            color=nextcord.Color.blue()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        return embed

    @nextcord.slash_command(name="counter", description="A personal counter.", guild_ids=[GUILD_ID])
    async def counter_command(self, interaction: Interaction):
        user_id = interaction.user.id
        
        await interaction.response.defer()

        counter_data = await self.get_user_counter_data(user_id)
        current_count = 0

        if not counter_data:
            # If no data exists, it's a fresh start.
            await self.update_user_counter(user_id, 0)
            current_count = 0
        else:
            # If data exists, just use that count.
            # The timeout logic will handle deletion.
            current_count = counter_data["count"]

        embed = self._create_embed(interaction, current_count)
        view = CounterView(owner_id=user_id, counter_cog=self)

        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message


# --- UI Views ---

class CounterView(nextcord.ui.View):
    def __init__(self, owner_id: int, counter_cog: 'Counter'):
        super().__init__(timeout=86400.0)  # 24 hours
        self.owner_id = owner_id
        self.message: nextcord.Message = None
        self.counter_cog = counter_cog

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This is not your counter!", ephemeral=True)
            return False
        return True

    async def _update_display(self, interaction: Interaction, new_count: int):
        embed = self.message.embeds[0]
        embed.title = f"Count: **{new_count}**"
        
        # Defer if not already done, then edit
        if not interaction.response.is_done():
            await interaction.response.defer()
        await interaction.followup.edit_message(message_id=self.message.id, embed=embed)


    @nextcord.ui.button(label="Increment", style=nextcord.ButtonStyle.green, custom_id="increment_counter")
    async def increment_button(self, button: nextcord.ui.Button, interaction: Interaction):
        counter_data = await self.counter_cog.get_user_counter_data(self.owner_id)
        new_count = (counter_data["count"] + 1) if counter_data else 1
        await self.counter_cog.update_user_counter(self.owner_id, new_count)
        await self._update_display(interaction, new_count)

    @nextcord.ui.button(label="Reset", style=nextcord.ButtonStyle.red, custom_id="reset_counter")
    async def reset_button(self, button: nextcord.ui.Button, interaction: Interaction):
        await self.counter_cog.update_user_counter(self.owner_id, 0)
        await self._update_display(interaction, 0)

    async def on_timeout(self):
        """Disables buttons, updates the message, and deletes the DB record."""
        # Disable all buttons
        for item in self.children:
            item.disabled = True

        # Stop the view from listening for interactions
        self.stop()
        
        # Delete the counter from the database
        # This is the critical fix.
        await self.counter_cog.delete_user_counter(self.owner_id)

        # Update the message to show it has expired
        if self.message and self.message.embeds:
            embed = self.message.embeds[0]
            embed.description = "*This counter has expired.*"
            embed.color = nextcord.Color.greyple()
            try:
                await self.message.edit(embed=embed, view=self)
            except nextcord.NotFound:
                # Message was deleted, nothing to do
                pass
            except Exception as e:
                print(f"Error editing message on timeout: {e}")

# Setup function for the cog
async def setup(bot):
    cog = Counter(bot)
    await cog.create_tables()
    bot.add_cog(cog)
    print("CounterCog loaded.")