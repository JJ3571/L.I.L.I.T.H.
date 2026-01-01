import asyncio
import datetime
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import aiosqlite
import nextcord
from nextcord import Interaction
from nextcord.ext import commands, tasks

from server_configs.config import GUILD_ID
from server_configs.database_config import DATABASE_PATHS
from utils.brave_image_helper import BraveImageError, download_and_save_image, fetch_image_for_term
from utils.tierlist_image_generator import TIER_ORDER, generate_tierlist_image

logger = logging.getLogger(__name__)

DB_PATH = DATABASE_PATHS["tierlist"]
IMAGES_ROOT_DIR = os.path.join("databases", "tierlist_images")

TIER_SCORES: Dict[str, int] = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
SCORE_TO_TIER: Dict[int, str] = {v: k for k, v in TIER_SCORES.items()}

OPTIONS_SPLIT_RE = re.compile(r"[;,.]\s*|\n+")


def utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_iso_dt(value: str) -> datetime.datetime:
    # Stored as ISO w/ timezone
    return datetime.datetime.fromisoformat(value)


def clamp_int(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


class TierListError(Exception):
    pass


class TierListOptionsModal(nextcord.ui.Modal):
    def __init__(self, *, cog: "TierList", title: str, mode: str, duration_hours: int):
        super().__init__(title="Tier list options")
        self.cog = cog
        self.list_title = title
        self.mode = mode
        self.duration_hours = duration_hours

        self.options_input = nextcord.ui.TextInput(
            label="Options (comma/semicolon/period separated)",
            placeholder="Iron Man, Spider-Man; Thor. Hulk",
            required=True,
            max_length=1800,
            style=nextcord.TextInputStyle.paragraph,
        )
        self.add_item(self.options_input)

    async def callback(self, interaction: Interaction) -> None:
        raw = (self.options_input.value or "").strip()
        options = [o.strip() for o in OPTIONS_SPLIT_RE.split(raw) if o.strip()]

        if not options:
            await interaction.response.send_message("No options found. Please try again.", ephemeral=True)
            return

        if len(options) > 25:
            options = options[:25]

        await interaction.response.send_message(
            f"Creating tier list **{self.list_title}** with **{len(options)}** options…",
            ephemeral=True,
        )

        try:
            await self.cog.create_tierlist_from_modal(
                interaction=interaction,
                title=self.list_title,
                mode=self.mode,
                duration_hours=self.duration_hours,
                options=options,
            )
        except Exception as e:
            logger.exception("Failed to create tier list: %s", e)
            await interaction.followup.send("Failed to create tier list. Please try again later.", ephemeral=True)


class TierListMainView(nextcord.ui.View):
    def __init__(self, *, list_id: int, creator_id: int, cog: "TierList"):
        super().__init__(timeout=None)  # persistent
        self.list_id = list_id
        self.creator_id = creator_id
        self.cog = cog

        self.vote_button.custom_id = f"tierlist_vote_{list_id}"
        self.finish_button.custom_id = f"tierlist_finish_{list_id}"

    @nextcord.ui.button(label="Vote", style=nextcord.ButtonStyle.blurple, custom_id="tierlist_vote_0")
    async def vote_button(self, button: nextcord.ui.Button, interaction: Interaction):
        await self.cog.handle_vote_button(interaction, self.list_id)

    @nextcord.ui.button(label="Finish", style=nextcord.ButtonStyle.red, custom_id="tierlist_finish_0")
    async def finish_button(self, button: nextcord.ui.Button, interaction: Interaction):
        await self.cog.handle_finish_button(interaction, self.list_id)


class TierListTierSelect(nextcord.ui.Select):
    def __init__(self):
        options = [
            nextcord.SelectOption(label=tier, value=tier, description=f"Vote {tier}") for tier in TIER_ORDER
        ]
        super().__init__(placeholder="Select a tier…", min_values=1, max_values=1, options=options, custom_id="tierlist_tier_select")


class TierListOptionSelect(nextcord.ui.Select):
    def __init__(self, *, option_rows: List[aiosqlite.Row]):
        options: List[nextcord.SelectOption] = []
        for r in option_rows:
            text = str(r["option_text"])
            label = text if len(text) <= 95 else text[:94] + "…"
            options.append(nextcord.SelectOption(label=label, value=str(r["option_id"])))

        super().__init__(
            placeholder="Revote: pick an option…",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id="tierlist_option_select",
        )


class TierListVotingView(nextcord.ui.View):
    def __init__(self, *, list_id: int, voter_id: int, creator_id: int, mode: str, cog: "TierList"):
        super().__init__(timeout=3600)
        self.list_id = list_id
        self.voter_id = voter_id
        self.creator_id = creator_id
        self.mode = mode
        self.cog = cog

        self.selected_tier: Optional[str] = None
        self.selected_option_id: Optional[int] = None
        self.tier_select = TierListTierSelect()
        self.tier_select.callback = self._on_tier_select
        self.add_item(self.tier_select)

        # added later once all voted:
        self.option_select: Optional[TierListOptionSelect] = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        if self.mode == "personal" and interaction.user.id != self.creator_id:
            await interaction.response.send_message("Only the tier list creator can vote on this one.", ephemeral=True)
            return False
        if interaction.user.id != self.voter_id:
            await interaction.response.send_message("This voting session belongs to someone else.", ephemeral=True)
            return False
        return True

    async def _on_tier_select(self, interaction: Interaction):
        self.selected_tier = self.tier_select.values[0]
        await interaction.response.defer()

    @nextcord.ui.button(label="Submit vote", style=nextcord.ButtonStyle.green, custom_id="tierlist_submit_vote")
    async def submit_vote(self, button: nextcord.ui.Button, interaction: Interaction):
        await self.cog.handle_submit_vote(interaction, view=self)

    @nextcord.ui.button(label="Done voting", style=nextcord.ButtonStyle.secondary, custom_id="tierlist_done_voting")
    async def done_voting(self, button: nextcord.ui.Button, interaction: Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def attach_revote_dropdown(self, option_rows: List[aiosqlite.Row]) -> None:
        # if already present, do nothing
        if self.option_select is not None:
            return
        self.option_select = TierListOptionSelect(option_rows=option_rows)
        self.option_select.callback = self._on_option_select
        self.add_item(self.option_select)

    async def _on_option_select(self, interaction: Interaction):
        raw = self.option_select.values[0]
        try:
            self.selected_option_id = int(raw)
        except Exception:
            self.selected_option_id = None
        await interaction.response.defer()


class TierList(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = DB_PATH
        self._session: Optional[aiohttp.ClientSession] = None

        self.bot.loop.create_task(self.add_persistent_views())
        self.auto_finish_expired.start()

    async def cog_unload(self):
        try:
            self.auto_finish_expired.cancel()
        except Exception:
            pass
        if self._session:
            await self._session.close()

    async def cog_load(self):
        await self.create_tables()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession()
        return self._session

    async def create_tables(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tier_lists (
                    list_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    list_title TEXT NOT NULL,
                    list_mode TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    duration_hours INTEGER DEFAULT 24,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    message_id INTEGER,
                    channel_id INTEGER
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tier_options (
                    option_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id INTEGER NOT NULL,
                    option_text TEXT NOT NULL,
                    option_index INTEGER NOT NULL,
                    image_url TEXT,
                    local_image_path TEXT,
                    FOREIGN KEY (list_id) REFERENCES tier_lists(list_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tier_votes (
                    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id INTEGER NOT NULL,
                    option_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    tier_rank TEXT NOT NULL,
                    tier_score INTEGER NOT NULL,
                    voted_at TEXT NOT NULL,
                    UNIQUE(list_id, option_id, user_id),
                    FOREIGN KEY (list_id) REFERENCES tier_lists(list_id),
                    FOREIGN KEY (option_id) REFERENCES tier_options(option_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_voting_progress (
                    progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    current_option_index INTEGER DEFAULT 0,
                    is_complete INTEGER DEFAULT 0,
                    UNIQUE(list_id, user_id),
                    FOREIGN KEY (list_id) REFERENCES tier_lists(list_id)
                )
                """
            )
            await db.commit()

    @tasks.loop(minutes=60)
    async def auto_finish_expired(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.now(datetime.timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT list_id FROM tier_lists WHERE status='active' AND expires_at <= ?",
                (now.isoformat(),),
            )
        for r in rows:
            try:
                await self.finish_tierlist(list_id=int(r["list_id"]), finished_by_user_id=None)
            except Exception:
                logger.exception("Auto-finish failed for list_id=%s", r["list_id"])

    @auto_finish_expired.before_loop
    async def _before_auto_finish(self):
        await self.bot.wait_until_ready()

    @nextcord.slash_command(name="tierlist", description="Create a tier list", guild_ids=[GUILD_ID])
    async def tierlist(self, interaction: Interaction):
        # Placeholder parent command. Users should use subcommands.
        await interaction.response.send_message("Use `/tierlist create`.", ephemeral=True)

    @tierlist.subcommand(name="create", description="Create a tier list", guild_ids=[GUILD_ID])
    async def tierlist_create(
        self,
        interaction: Interaction,
        title: str = nextcord.SlashOption(description="Tier list title", required=True, max_length=80),
        mode: str = nextcord.SlashOption(
            description="Personal = only you can vote; Server = everyone can vote",
            required=True,
            choices={"personal": "personal", "server": "server"},
        ),
        duration_hours: int = nextcord.SlashOption(description="How long voting stays open", required=False, default=24),
    ):
        duration_hours = clamp_int(int(duration_hours), 1, 168)
        await interaction.response.send_modal(
            TierListOptionsModal(cog=self, title=title, mode=mode, duration_hours=duration_hours)
        )

    async def create_tierlist_from_modal(
        self,
        *,
        interaction: Interaction,
        title: str,
        mode: str,
        duration_hours: int,
        options: List[str],
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        expires = now + datetime.timedelta(hours=duration_hours)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                INSERT INTO tier_lists (guild_id, creator_id, list_title, list_mode, status, duration_hours, created_at, expires_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (interaction.guild_id or 0, interaction.user.id, title, mode, duration_hours, now.isoformat(), expires.isoformat()),
            )
            list_id = cur.lastrowid

            option_ids: List[int] = []
            for idx, opt in enumerate(options):
                cur2 = await db.execute(
                    "INSERT INTO tier_options (list_id, option_text, option_index) VALUES (?, ?, ?)",
                    (list_id, opt, idx),
                )
                option_ids.append(cur2.lastrowid)
            await db.commit()

        # Fetch images best-effort (async, limited concurrency)
        try:
            await self._fetch_images_for_list(list_id=list_id, title=title, option_ids=option_ids)
        except Exception:
            logger.exception("Image fetch failed for list_id=%s (continuing without images)", list_id)

        embed = await self._build_main_embed(list_id=list_id)
        view = TierListMainView(list_id=list_id, creator_id=interaction.user.id, cog=self)

        # Send main tier list message to channel (non-ephemeral)
        message = await interaction.channel.send(embed=embed, view=view)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE tier_lists SET message_id=?, channel_id=? WHERE list_id=?",
                (message.id, message.channel.id, list_id),
            )
            await db.commit()

        await interaction.followup.send(f"Tier list created: [message link]({message.jump_url})", ephemeral=True)

        # Ensure this view is registered for persistence immediately
        self.bot.add_view(view)

    async def _fetch_images_for_list(self, *, list_id: int, title: str, option_ids: List[int]) -> None:
        # Pull option text from DB; then for each option do Brave search + download.
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT option_id, option_text FROM tier_options WHERE list_id=? ORDER BY option_index ASC",
                (list_id,),
            )

        session = await self._get_session()
        sem = asyncio.Semaphore(3)

        async def process_one(r: aiosqlite.Row):
            async with sem:
                opt_id = int(r["option_id"])
                opt_text = str(r["option_text"])
                try:
                    result = await fetch_image_for_term(session, title, opt_text, count=1)
                    if not result:
                        return
                    out_dir = os.path.join(IMAGES_ROOT_DIR, str(list_id))
                    out_path = os.path.join(out_dir, f"{opt_id}.jpg")
                    saved_path = await download_and_save_image(session, result.url, output_path=out_path)
                    async with aiosqlite.connect(self.db_path) as db2:
                        await db2.execute(
                            "UPDATE tier_options SET image_url=?, local_image_path=? WHERE option_id=?",
                            (result.url, saved_path, opt_id),
                        )
                        await db2.commit()
                except BraveImageError:
                    # best-effort; ignore
                    return
                except Exception:
                    return

        await asyncio.gather(*[process_one(r) for r in rows])

    async def _build_main_embed(self, *, list_id: int) -> nextcord.Embed:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchone("SELECT * FROM tier_lists WHERE list_id=?", (list_id,))
            if not row:
                raise TierListError("Tier list not found")

            options_count = await db.execute_fetchone(
                "SELECT COUNT(*) AS c FROM tier_options WHERE list_id=?", (list_id,)
            )

        embed = nextcord.Embed(
            title=f"Tier List: {row['list_title']}",
            description=(
                f"Mode: **{row['list_mode']}**\n"
                f"Status: **{row['status']}**\n"
                f"Options: **{int(options_count['c'])}**\n"
                f"Ends: <t:{int(parse_iso_dt(row['expires_at']).timestamp())}:R>"
            ),
            color=nextcord.Color.blurple(),
        )
        embed.set_footer(text=f"List ID: {list_id}")
        return embed

    async def add_persistent_views(self):
        await self.bot.wait_until_ready()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT list_id, creator_id FROM tier_lists WHERE status='active'"
            )
        for r in rows:
            try:
                view = TierListMainView(list_id=int(r["list_id"]), creator_id=int(r["creator_id"]), cog=self)
                self.bot.add_view(view)
            except Exception:
                logger.exception("Failed to add persistent view for list_id=%s", r["list_id"])

    async def handle_vote_button(self, interaction: Interaction, list_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            tl = await db.execute_fetchone("SELECT * FROM tier_lists WHERE list_id=?", (list_id,))
            if not tl:
                await interaction.response.send_message("Tier list not found.", ephemeral=True)
                return
            if tl["status"] != "active":
                await interaction.response.send_message("This tier list is finished.", ephemeral=True)
                return
            creator_id = int(tl["creator_id"])
            mode = str(tl["list_mode"])

        voter_id = interaction.user.id
        view = TierListVotingView(list_id=list_id, voter_id=voter_id, creator_id=creator_id, mode=mode, cog=self)
        embed = await self._build_voting_embed(list_id=list_id, voter_id=voter_id, option_id=None)

        ephemeral = True if mode == "server" else False
        await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)

        # After sending, update to the next option (first not yet voted), by editing original response
        try:
            next_opt_id = await self._get_next_option_to_vote(list_id=list_id, user_id=voter_id)
            embed2 = await self._build_voting_embed(list_id=list_id, voter_id=voter_id, option_id=next_opt_id)
            await interaction.edit_original_message(embed=embed2, view=view)
        except Exception:
            pass

    async def _build_voting_embed(
        self,
        *,
        list_id: int,
        voter_id: int,
        option_id: Optional[int],
    ) -> nextcord.Embed:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            tl = await db.execute_fetchone("SELECT * FROM tier_lists WHERE list_id=?", (list_id,))
            if not tl:
                raise TierListError("Tier list not found")

            option_row = None
            if option_id is not None:
                option_row = await db.execute_fetchone(
                    "SELECT * FROM tier_options WHERE option_id=? AND list_id=?",
                    (option_id, list_id),
                )

            total_row = await db.execute_fetchone(
                "SELECT COUNT(*) AS c FROM tier_options WHERE list_id=?",
                (list_id,),
            )
            voted_row = await db.execute_fetchone(
                """
                SELECT COUNT(DISTINCT option_id) AS c
                FROM tier_votes
                WHERE list_id=? AND user_id=?
                """,
                (list_id, voter_id),
            )

        desc = f"Progress: **{int(voted_row['c'])}/{int(total_row['c'])}** options voted."
        if option_row is None:
            desc += "\nSelect a tier, then hit **Submit vote**."
        else:
            desc += f"\n\nNow voting: **{option_row['option_text']}**"

        embed = nextcord.Embed(
            title=f"Voting: {tl['list_title']}",
            description=desc,
            color=nextcord.Color.green(),
        )
        embed.set_footer(text=f"List ID: {list_id} • Voter: {voter_id}")

        if option_row is not None and option_row.get("local_image_path"):
            # show image by attaching URL if we can; local file can't be embedded without attachment.
            # We'll show the remote URL and keep local for the final composite render.
            if option_row.get("image_url"):
                embed.set_image(url=str(option_row["image_url"]))

        return embed

    async def _get_next_option_to_vote(self, *, list_id: int, user_id: int) -> Optional[int]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchone(
                """
                SELECT o.option_id
                FROM tier_options o
                WHERE o.list_id=?
                  AND o.option_id NOT IN (
                    SELECT option_id FROM tier_votes WHERE list_id=? AND user_id=?
                  )
                ORDER BY o.option_index ASC
                LIMIT 1
                """,
                (list_id, list_id, user_id),
            )
            return int(row["option_id"]) if row else None

    async def _get_all_options(self, *, list_id: int) -> List[aiosqlite.Row]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            return await db.execute_fetchall(
                "SELECT option_id, option_text FROM tier_options WHERE list_id=? ORDER BY option_index ASC",
                (list_id,),
            )

    async def handle_submit_vote(self, interaction: Interaction, *, view: TierListVotingView) -> None:
        if not view.selected_tier:
            await interaction.response.send_message("Pick a tier first.", ephemeral=True)
            return

        # Determine which option we're voting on:
        option_id = view.selected_option_id
        if option_id is None:
            option_id = await self._get_next_option_to_vote(list_id=view.list_id, user_id=view.voter_id)
        if option_id is None:
            # all voted; require revote dropdown
            await interaction.response.send_message(
                "All options are voted. Use the revote dropdown to change an option.",
                ephemeral=True,
            )
            return

        tier = view.selected_tier
        score = int(TIER_SCORES.get(tier, 0))

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tier_votes (list_id, option_id, user_id, tier_rank, tier_score, voted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(list_id, option_id, user_id)
                DO UPDATE SET tier_rank=excluded.tier_rank, tier_score=excluded.tier_score, voted_at=excluded.voted_at
                """,
                (view.list_id, option_id, view.voter_id, tier, score, utcnow_iso()),
            )
            await db.commit()

        # Reset selection so user has to choose again
        view.selected_tier = None
        view.selected_option_id = None

        # If completed, attach revote dropdown
        next_opt_id = await self._get_next_option_to_vote(list_id=view.list_id, user_id=view.voter_id)
        if next_opt_id is None:
            option_rows = await self._get_all_options(list_id=view.list_id)
            await view.attach_revote_dropdown(option_rows)

        embed = await self._build_voting_embed(list_id=view.list_id, voter_id=view.voter_id, option_id=next_opt_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def handle_finish_button(self, interaction: Interaction, list_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            tl = await db.execute_fetchone("SELECT * FROM tier_lists WHERE list_id=?", (list_id,))
            if not tl:
                await interaction.response.send_message("Tier list not found.", ephemeral=True)
                return
            if interaction.user.id != int(tl["creator_id"]):
                await interaction.response.send_message("Only the creator can finish this tier list.", ephemeral=True)
                return
            if tl["status"] != "active":
                await interaction.response.send_message("This tier list is already finished.", ephemeral=True)
                return

        await interaction.response.defer()
        await self.finish_tierlist(list_id=list_id, finished_by_user_id=interaction.user.id, interaction=interaction)

    async def finish_tierlist(
        self,
        *,
        list_id: int,
        finished_by_user_id: Optional[int],
        interaction: Optional[Interaction] = None,
    ) -> None:
        # Mark finished
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            tl = await db.execute_fetchone("SELECT * FROM tier_lists WHERE list_id=?", (list_id,))
            if not tl:
                return
            if tl["status"] != "active":
                return
            await db.execute("UPDATE tier_lists SET status='finished' WHERE list_id=?", (list_id,))
            await db.commit()

        # Build aggregated results + render image
        tier_to_items = await self.aggregate_votes(list_id=list_id)
        out_dir = os.path.join(IMAGES_ROOT_DIR, str(list_id))
        out_path = os.path.join(out_dir, "final_tierlist.png")
        generate_tierlist_image(output_path=out_path, tier_to_items=tier_to_items, title=str(tl["list_title"]))

        # Send final image to original channel if we can
        channel = None
        try:
            if tl["channel_id"]:
                channel = self.bot.get_channel(int(tl["channel_id"]))
        except Exception:
            channel = None

        embed = nextcord.Embed(
            title=f"Final Tier List: {tl['list_title']}",
            description="Voting finished. Results below.",
            color=nextcord.Color.gold(),
        )

        file = nextcord.File(out_path, filename="final_tierlist.png")
        embed.set_image(url="attachment://final_tierlist.png")

        if interaction is not None:
            await interaction.followup.send(embed=embed, file=file)
        elif channel is not None:
            await channel.send(embed=embed, file=file)

        # Try to disable main message buttons if message still exists
        try:
            if tl["channel_id"] and tl["message_id"]:
                ch = self.bot.get_channel(int(tl["channel_id"]))
                if ch:
                    msg = await ch.fetch_message(int(tl["message_id"]))
                    done_embed = await self._build_main_embed(list_id=list_id)
                    done_embed.color = nextcord.Color.greyple()
                    done_embed.description = (done_embed.description or "") + "\n\n*Finished.*"
                    await msg.edit(embed=done_embed, view=None)
        except Exception:
            pass

    async def aggregate_votes(self, *, list_id: int) -> Dict[str, List[Dict[str, Any]]]:
        # default empty lists
        tier_to_items: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TIER_ORDER}

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            options = await db.execute_fetchall(
                "SELECT option_id, option_text, local_image_path FROM tier_options WHERE list_id=? ORDER BY option_index ASC",
                (list_id,),
            )

            for opt in options:
                votes = await db.execute_fetchall(
                    "SELECT tier_score FROM tier_votes WHERE list_id=? AND option_id=?",
                    (list_id, opt["option_id"]),
                )
                if not votes:
                    # If no votes, put in C as a neutral bucket
                    final_tier = "C"
                else:
                    avg = sum(int(v["tier_score"]) for v in votes) / len(votes)
                    final_score = int(round(avg))
                    final_score = clamp_int(final_score, 0, 5)
                    final_tier = SCORE_TO_TIER.get(final_score, "C")

                tier_to_items[final_tier].append(
                    {"text": str(opt["option_text"]), "image_path": opt["local_image_path"]}
                )

        return tier_to_items


def setup(bot: commands.Bot):
    bot.add_cog(TierList(bot))



