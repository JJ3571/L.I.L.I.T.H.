import asyncio
import datetime
import logging
import os
import re
import shutil
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import nextcord
from nextcord import Interaction, SlashOption, TextInputStyle
from nextcord.ext import commands, tasks

from main_bot.paths import PROJECT_ROOT
from main_bot.server_configs.config import BRAVE_SEARCH_API_KEY, GUILD_ID, admin_user_ids
from main_bot.utils.brave_image_helper import (
    BraveImageError,
    fetch_brave_image_result_rows,
    filter_brave_rows_to_previewable,
    search_and_save_brave_option_image,
    tierlist_image_min_size_px,
    tierlist_option_image_search_query,
    try_save_image_from_brave_result_row,
)
from main_bot.utils.tierlist_image_generator import TIER_ORDER, generate_tierlist_image

logger = logging.getLogger(__name__)

_TL = "tierlist"
ITEMS_SUBDIR = os.fspath(PROJECT_ROOT / "data" / "tierlist" / "items")
FINAL_SUBDIR = os.fspath(PROJECT_ROOT / "data" / "tierlist" / "final")
LIVE_IMAGE_FILENAME = "live_tierlist.png"
VOTE_ITEM_FILENAME = "vote_item.jpg"
PICK_PREVIEW_FILENAME = "option_preview.jpg"
# How many Brave search pages (× count per request) to walk when every hit on a page fails preview.
_PICKER_MAX_BRAVE_PAGES = 8

TIER_SCORES: Dict[str, int] = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0, "N/A": -1}
SCORE_TO_TIER: Dict[int, str] = {v: k for k, v in TIER_SCORES.items()}

# Only comma, semicolon, or newline — not ".", so names like "Dr. Strange" stay one option.
OPTIONS_SPLIT_RE = re.compile(r"[;,]\s*|\n+")


def _parse_tierlist_duration_hours(raw: str) -> Optional[int]:
    """Empty → 24; otherwise integer in 1…168, or ``None`` if invalid."""
    t = (raw or "").strip()
    if not t:
        return 24
    try:
        v = int(t, 10)
    except ValueError:
        return None
    return clamp_int(int(v), 1, 168)


def _item_dir(list_id: int) -> str:
    return os.path.join(ITEMS_SUBDIR, str(list_id))


def _final_dir(list_id: int) -> str:
    return os.path.join(FINAL_SUBDIR, str(list_id))


def _live_png_path(list_id: int) -> str:
    return os.path.join(_item_dir(list_id), LIVE_IMAGE_FILENAME)


def _final_png_path(list_id: int) -> str:
    return os.path.join(_final_dir(list_id), "final_tierlist.png")


def utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_iso_dt(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


_EN_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _tierlist_created_dt(value: str) -> datetime.datetime:
    s = (value or "").strip().replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _tierlist_show_choice_label(created_at_str: str, title: str) -> str:
    """e.g. ``Apr '26 - Best Superhero`` (English month; max 100 chars for Discord)."""
    dt = _tierlist_created_dt(created_at_str)
    prefix = f"{_EN_MON[dt.month - 1]} '{dt.year % 100:02d} - "
    t = (title or "").strip() or "(untitled)"
    room = max(1, 100 - len(prefix))
    if len(t) > room:
        t = t[: max(0, room - 1)] + "…"
    return prefix + t


def _unique_autocomplete_dict(names_to_values: List[Tuple[str, str]]) -> Dict[str, str]:
    """Discord choice names must be unique; values are list_id strings."""
    out: Dict[str, str] = {}
    used: set = set()
    for name, value in names_to_values:
        candidate = name[:100]
        if candidate not in used:
            used.add(candidate)
            out[candidate] = value
            continue
        suf = f" #{value}"
        candidate = (name[: max(0, 100 - len(suf))] + suf)[:100]
        n = 1
        while candidate in used:
            suf = f" #{value}:{n}"
            candidate = (name[: max(0, 100 - len(suf))] + suf)[:100]
            n += 1
        used.add(candidate)
        out[candidate] = value
    return out


def clamp_int(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def _tierlist_image_subtitle(*, list_status: str, n_votes: Optional[int] = None) -> str:
    """Human-readable line for the PNG (matches DB `tier_lists.status` when present)."""
    s = (list_status or "active").strip().lower()
    if s == "active" and n_votes is not None:
        return f"Status: Live — {n_votes} vote(s) recorded"
    if s == "finished":
        return "Status: Complete"
    return f"Status: {s.replace('_', ' ').title()}"


class TierListError(Exception):
    pass


class TierListCreateVotingView(nextcord.ui.View):
    """
    Discord modals can only include text fields (no checkboxes). This view is a one-tap
    stand-in: Server vs Personal, then the real ``TierListOptionsModal`` opens.
    """

    def __init__(self, *, cog: "TierList", user_id: int) -> None:
        super().__init__(timeout=300.0)
        self.cog = cog
        self._user_id = user_id

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("This setup is not for you.", ephemeral=True)
            return False
        return True

    async def _open_modal(self, interaction: Interaction, mode: str) -> None:
        await interaction.response.send_modal(TierListOptionsModal(cog=self.cog, mode=mode))
        for ch in self.children:
            if isinstance(ch, nextcord.ui.Button):
                ch.disabled = True
        try:
            if interaction.message is not None:
                await interaction.message.edit(view=self)
        except Exception:
            logger.debug("Could not disable tierlist create voting buttons", exc_info=True)
        self.stop()

    @nextcord.ui.button(label="Server — everyone can vote", style=nextcord.ButtonStyle.primary, row=0)
    async def server(self, _btn: nextcord.ui.Button, interaction: Interaction) -> None:
        await self._open_modal(interaction, "server")

    @nextcord.ui.button(
        label="Personal — only you can vote", style=nextcord.ButtonStyle.secondary, row=0
    )
    async def personal(self, _btn: nextcord.ui.Button, interaction: Interaction) -> None:
        await self._open_modal(interaction, "personal")


class TierListOptionsModal(nextcord.ui.Modal):
    def __init__(self, *, cog: "TierList", mode: str):
        super().__init__(title="Create tier list")
        self.cog = cog
        self.mode = mode if mode in ("server", "personal") else "server"

        self.title_input = nextcord.ui.TextInput(
            label="Tierlist Title",
            style=TextInputStyle.short,
            required=True,
            max_length=80,
            placeholder="e.g. Best Marvel heroes",
        )
        self.duration_input = nextcord.ui.TextInput(
            label="Duration (hours voting is open for)",
            style=TextInputStyle.short,
            required=False,
            max_length=4,
            placeholder="Default 24. Up to 168hrs",
        )
        self.image_prefix_input = nextcord.ui.TextInput(
            label="Image search prefix",
            style=TextInputStyle.short,
            required=False,
            max_length=200,
            placeholder="For better image results. Added before the option name.",
        )
        self.options_input = nextcord.ui.TextInput(
            label="Options (Split with \",\" \";\" or a new line)",
            placeholder="Iron Man, Dr. Strange; Thor, Hulk\n\nSpiderman\nWolverine\nBlack Panther",
            required=True,
            max_length=1800,
            style=TextInputStyle.paragraph,
        )
        self.add_item(self.title_input)
        self.add_item(self.duration_input)
        self.add_item(self.image_prefix_input)
        self.add_item(self.options_input)

    async def callback(self, interaction: Interaction) -> None:
        list_title = (self.title_input.value or "").strip()
        if not list_title:
            await interaction.response.send_message("Please enter a **title**.", ephemeral=True)
            return

        mode = self.mode

        dh = _parse_tierlist_duration_hours(self.duration_input.value or "")
        if dh is None:
            await interaction.response.send_message(
                "Duration must be a whole number of **hours** between **1** and **168** (or leave empty for 24).",
                ephemeral=True,
            )
            return

        raw = (self.options_input.value or "").strip()
        options = [o.strip() for o in OPTIONS_SPLIT_RE.split(raw) if o.strip()]

        if not options:
            await interaction.response.send_message("No options found. Please try again.", ephemeral=True)
            return

        if len(options) > 25:
            options = options[:25]

        image_prefix = (self.image_prefix_input.value or "").strip() or None

        await interaction.response.send_message(
            f"Creating tier list **{list_title}** with **{len(options)}** options…",
            ephemeral=True,
        )

        try:
            await self.cog.create_tierlist_from_modal(
                interaction=interaction,
                title=list_title,
                mode=mode,
                duration_hours=dh,
                options=options,
                image_search_prefix=image_prefix,
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
        self.settings_button.custom_id = f"tierlist_settings_{list_id}"
        self.finish_button.custom_id = f"tierlist_finish_{list_id}"

    @nextcord.ui.button(label="Vote", style=nextcord.ButtonStyle.blurple, custom_id="tierlist_vote_0", row=0)
    async def vote_button(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await self.cog.handle_vote_button(interaction, self.list_id)

    @nextcord.ui.button(label="⚙️", style=nextcord.ButtonStyle.secondary, custom_id="tierlist_settings_0", row=0)
    async def settings_button(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await self.cog.handle_settings_button(interaction, self.list_id)

    @nextcord.ui.button(label="Finish", style=nextcord.ButtonStyle.red, custom_id="tierlist_finish_0", row=0)
    async def finish_button(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await self.cog.handle_finish_button(interaction, self.list_id)


async def _edit_tierlist_picker_message(
    interaction: Interaction,
    *,
    embed: nextcord.Embed,
    file: Optional[nextcord.File],
    view: Optional[nextcord.ui.View],
    message_id: Optional[int] = None,
) -> None:
    """
    Ephemeral (and other) *followup* messages are not in the channel; :meth:`Message.edit`
    uses the channel API and returns 404. Edits must go through
    :meth:`Interaction.followup.edit_message` (interaction webhook), using ``file=`` for new bytes
    (not ``attachments=`` with :class:`File`).

    ``message_id`` is required when the interaction has no ``message`` (e.g. some modal submissions).
    """
    mid: Optional[int] = message_id
    if mid is None and interaction.message is not None:
        mid = int(interaction.message.id)
    if mid is None:
        raise ValueError("message_id or interaction.message is required to edit the picker")
    if file is not None:
        await interaction.followup.edit_message(
            mid, embed=embed, file=file, view=view
        )  # type: ignore[union-attr]
    else:
        # Without clearing attachments, Discord keeps the previous image bytes — the
        # embed/ footer update but the picture looks "stuck".
        await interaction.followup.edit_message(
            mid, embed=embed, view=view, attachments=[]
        )  # type: ignore[union-attr]


class TierListOptionImageView(nextcord.ui.View):
    """Cycle Brave image results per option; used at list creation (creator) and in admin settings."""

    def __init__(
        self,
        *,
        cog: "TierList",
        list_id: int,
        list_title: str,
        user_id: int,
        channel_id: int,
        options: List[Dict[str, Any]],
        flow: str,
        image_search_prefix: Optional[str] = None,
    ) -> None:
        super().__init__(timeout=1800.0)
        self.cog = cog
        self.list_id = list_id
        self.list_title = list_title
        p = (image_search_prefix or "").strip()
        self._image_search_prefix: Optional[str] = p or None
        self.user_id = user_id
        self.channel_id = channel_id
        self.options = options
        self.flow = flow
        self.opt_i = 0
        self.brave_rows: List[Dict[str, Any]] = []
        self.result_idx = 0
        self.next_api_offset = 0
        self._last_url: Optional[str] = None
        self._warn: str = ""
        self._search_query: str = ""
        self._picker_message_id: Optional[int] = None
        self._brave_query_overrides: Dict[int, str] = {}

    def _option_id(self) -> int:
        return int(self.options[self.opt_i]["option_id"])

    def _default_brave_query(self) -> str:
        return tierlist_option_image_search_query(
            str(self.options[self.opt_i]["option_text"]),
            image_search_prefix=self._image_search_prefix,
        )

    def _effective_brave_query(self) -> str:
        o = str(self._brave_query_overrides.get(self._option_id(), "")).strip()
        if o:
            return o
        return self._default_brave_query()

    def _sync_picker_message_id(self, interaction: Interaction) -> None:
        if self._picker_message_id is None and interaction.message is not None:
            self._picker_message_id = int(interaction.message.id)

    async def _edit_picker(
        self, interaction: Interaction, embed: nextcord.Embed, file: Optional[nextcord.File]
    ) -> None:
        self._sync_picker_message_id(interaction)
        await _edit_tierlist_picker_message(
            interaction,
            embed=embed,
            file=file,
            view=self,
            message_id=self._picker_message_id,
        )

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This setup is not for you.", ephemeral=True)
            return False
        return True

    def _path_for(self, option_id: int) -> str:
        return os.path.join(_item_dir(self.list_id), f"{option_id}.jpg")

    async def _ensure_rows_for_option(self) -> str:
        self._warn = ""
        if not BRAVE_SEARCH_API_KEY:
            self.brave_rows = []
            self.result_idx = 0
            self.next_api_offset = 0
            return "No `BRAVE_SEARCH_API_KEY` — use **Skip** for each option or add a key."
        self.brave_rows = []
        self.result_idx = 0
        self.next_api_offset = 0
        session = await self.cog._get_session()
        mw, mh = tierlist_image_min_size_px()
        try:
            q = self._effective_brave_query()
            self._search_query = q
            off = 0
            for _ in range(_PICKER_MAX_BRAVE_PAGES):
                page, self.next_api_offset = await fetch_brave_image_result_rows(
                    session,
                    q,
                    count=20,
                    offset=off,
                    timeout_s=25,
                    min_source_width=mw,
                    min_source_height=mh,
                )
                if not page:
                    break
                good = await filter_brave_rows_to_previewable(session, page)
                self.brave_rows.extend(good)
                if self.brave_rows:
                    return ""
                off = self.next_api_offset
        except BraveImageError as e:
            return str(e)
        if not self.brave_rows:
            return (
                f"No working image previews for this option (min decode size {mw}×{mh} px). "
                "Try **Search terms** or **More results**, or **Skip**."
            )
        return ""

    async def _load_more_rows(self) -> str:
        if not BRAVE_SEARCH_API_KEY:
            return "Brave key is not configured."
        session = await self.cog._get_session()
        mw, mh = tierlist_image_min_size_px()
        off = int(self.next_api_offset)
        added = 0
        try:
            q = self._effective_brave_query()
            self._search_query = q
            for _ in range(_PICKER_MAX_BRAVE_PAGES):
                page, new_off = await fetch_brave_image_result_rows(
                    session,
                    q,
                    count=20,
                    offset=off,
                    timeout_s=25,
                    min_source_width=mw,
                    min_source_height=mh,
                )
                if not page:
                    if added:
                        return ""
                    return "No additional image results for this query."
                self.next_api_offset = new_off
                good = await filter_brave_rows_to_previewable(session, page)
                off = new_off
                if good:
                    self.brave_rows.extend(good)
                    added += len(good)
                    return ""
        except BraveImageError as e:
            return str(e)
        return (
            "No additional **working** image results (hits load as previews). "
            "Try **Search terms** or a different query."
        )

    async def build_embed_and_file(self) -> Tuple[nextcord.Embed, Optional[nextcord.File]]:
        opt = self.options[self.opt_i]
        oid = int(opt["option_id"])
        path = self._path_for(oid)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        desc = (
            f"**{opt['option_text']}**\n\n"
            "◀ / ▶ — previous / next result · **Search terms** — custom Brave query for this item · "
            "**Confirm** — use this image · **Skip** — no image for this option."
        )
        if self.flow == "create":
            desc += "\n\n*Tier list will be created after confirming the last picture.*"
        else:
            desc += "\n\n*Tier list images updated once you complete this task.*"

        embed = nextcord.Embed(
            title=f"Option image ({self.opt_i + 1}/{len(self.options)})",
            description=desc,
            color=nextcord.Color.dark_teal(),
        )
        if self._warn:
            embed.add_field(name="Notice", value=self._warn[:1020], inline=False)

        fq = (self._search_query or "")[:200]
        if not self.brave_rows:
            self._last_url = None
            embed.set_footer(text=f"List {self.list_id} · no previews loaded")
            return embed, None
        # Always clamp to current length (stale nrows + row[i] on another code path was a source of
        # IndexError if the list was shortened between awaits or in concurrent view callbacks).
        self.result_idx = self.result_idx % len(self.brave_rows)

        def set_result_footer() -> None:
            nr = len(self.brave_rows)
            if fq:
                if nr:
                    embed.set_footer(
                        text=f"q: {fq}\n{self.result_idx + 1}/{nr} · list {self.list_id} · next offset {self.next_api_offset}"
                    )
                else:
                    embed.set_footer(
                        text=f"q: {fq}\nlist {self.list_id} · next offset {self.next_api_offset}"
                    )
            else:
                if nr:
                    embed.set_footer(
                        text=f"Brave {self.result_idx + 1}/{nr} · list {self.list_id} · offset {self.next_api_offset}"
                    )
                else:
                    embed.set_footer(
                        text=f"Brave — list {self.list_id} · offset {self.next_api_offset}"
                    )

        session = await self.cog._get_session()
        # Rows are pre-filtered to previewable; on rare failure (transient) drop the row and retry.
        guard = 0
        while self.brave_rows and guard <= len(self.brave_rows) + 2:
            guard += 1
            nrow = len(self.brave_rows)
            if nrow == 0:
                break
            self.result_idx = self.result_idx % nrow
            row = self.brave_rows[self.result_idx]
            url = await try_save_image_from_brave_result_row(session, row, output_path=path)
            if url:
                self._last_url = url
                set_result_footer()
                embed.set_image(url=f"attachment://{PICK_PREVIEW_FILENAME}")
                return embed, nextcord.File(path, filename=PICK_PREVIEW_FILENAME)
            del self.brave_rows[self.result_idx]
            if self.result_idx >= len(self.brave_rows) and self.brave_rows:
                self.result_idx = 0

        self._last_url = None
        set_result_footer()
        if not self.brave_rows:
            note = "\n\n*No working preview left for this item — use **More results** or **Search terms**.*"
            embed.description = (embed.description or "") + note
        return embed, None

    async def _commit_and_advance(self, interaction: Interaction, accept_image: bool) -> None:
        opt = self.options[self.opt_i]
        oid = int(opt["option_id"])
        path = self._path_for(oid)
        async with self.cog.bot.pg_pool.acquire() as db:
            if accept_image and self._last_url and os.path.isfile(path):
                await db.execute(
                    f"""
                    UPDATE "{_TL}".tier_options SET image_url = $1, local_image_path = $2
                    WHERE option_id = $3
                    """,
                    self._last_url,
                    path,
                    oid,
                )
            else:
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                await db.execute(
                    f"""
                    UPDATE "{_TL}".tier_options SET image_url = NULL, local_image_path = NULL
                    WHERE option_id = $1
                    """,
                    oid,
                )

        self.opt_i += 1
        if self.opt_i >= len(self.options):
            await self._complete_flow(interaction)
            return
        w = await self._ensure_rows_for_option()
        self._warn = w
        emb, f = await self.build_embed_and_file()
        await self._edit_picker(interaction, emb, f)

    async def _complete_flow(self, interaction: Interaction) -> None:
        if self.flow == "create":
            await self.cog._finalize_tierlist_after_image_wizard(
                interaction, list_id=self.list_id, channel_id=self.channel_id, view_to_stop=self
            )
        else:
            await self.cog._refresh_main_tierlist_message(self.list_id)
            for ch in self.children:
                if isinstance(ch, nextcord.ui.Button):
                    ch.disabled = True
            em = nextcord.Embed(
                title="Image selection saved",
                description="The tier list message has been updated.",
                color=nextcord.Color.green(),
            )
            await _edit_tierlist_picker_message(
                interaction, embed=em, file=None, view=None, message_id=self._picker_message_id
            )
            self.stop()

    @nextcord.ui.button(label="◀", style=nextcord.ButtonStyle.secondary, row=0)
    async def prev_hit(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await interaction.response.defer()
        if not self.brave_rows:
            return
        n = len(self.brave_rows)
        self.result_idx = (self.result_idx - 1) % n
        emb, f = await self.build_embed_and_file()
        await self._edit_picker(interaction, emb, f)

    @nextcord.ui.button(label="▶", style=nextcord.ButtonStyle.secondary, row=0)
    async def next_hit(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await interaction.response.defer()
        if not self.brave_rows:
            return
        n = len(self.brave_rows)
        self.result_idx = (self.result_idx + 1) % n
        emb, f = await self.build_embed_and_file()
        await self._edit_picker(interaction, emb, f)

    @nextcord.ui.button(label="More results", style=nextcord.ButtonStyle.primary, row=0)
    async def more_results(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await interaction.response.defer()
        err = await self._load_more_rows()
        if err and not self.brave_rows:
            self._warn = err
        elif err:
            self._warn = err
        if self.result_idx >= len(self.brave_rows) and self.brave_rows:
            self.result_idx = len(self.brave_rows) - 1
        emb, f = await self.build_embed_and_file()
        await self._edit_picker(interaction, emb, f)

    @nextcord.ui.button(label="Search terms", style=nextcord.ButtonStyle.secondary, row=2)
    async def edit_brave_query(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        if not BRAVE_SEARCH_API_KEY:
            await interaction.response.send_message(
                "Brave image search is not configured.", ephemeral=True
            )
            return
        self._sync_picker_message_id(interaction)
        if self._picker_message_id is None:
            await interaction.response.send_message(
                "Could not identify the image picker. Try again from list creation or Settings.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(OptionBraveQueryModal(self))

    @nextcord.ui.button(label="Confirm", style=nextcord.ButtonStyle.success, row=1)
    async def confirm(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await interaction.response.defer()
        if self._last_url:
            await self._commit_and_advance(interaction, accept_image=True)
        else:
            await self._commit_and_advance(interaction, accept_image=False)

    @nextcord.ui.button(label="Skip (no image)", style=nextcord.ButtonStyle.secondary, row=1)
    async def skip(self, button: nextcord.ui.Button, interaction: Interaction) -> None:
        await interaction.response.defer()
        await self._commit_and_advance(interaction, accept_image=False)


class OptionBraveQueryModal(nextcord.ui.Modal):
    def __init__(self, pview: TierListOptionImageView) -> None:
        super().__init__(title="Custom image search", auto_defer=False)
        self._pview = pview
        oid = pview._option_id()
        cur = (pview._brave_query_overrides.get(oid) or "").strip()
        default = pview._default_brave_query()
        ph = f"Default (empty = this): {default}"
        if len(ph) > 100:
            ph = ph[:97] + "..."
        self._query = nextcord.ui.TextInput(
            label="Brave search text",
            style=TextInputStyle.paragraph,
            default_value=cur or None,
            required=False,
            max_length=400,
            placeholder=ph,
        )
        self.add_item(self._query)

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        v = self._pview
        oid = v._option_id()
        text = (self._query.value or "").strip()
        if text:
            v._brave_query_overrides[oid] = text
        else:
            v._brave_query_overrides.pop(oid, None)
        w = await v._ensure_rows_for_option()
        v._warn = w
        emb, f = await v.build_embed_and_file()
        await _edit_tierlist_picker_message(
            interaction,
            embed=emb,
            file=f,
            view=v,
            message_id=v._picker_message_id,
        )


def _voting_tier_label(tier: str) -> str:
    if tier == "N/A":
        return "N/A"
    return f"{tier}"
    # Incase you want the score included in the button lablel:
    # return f"{tier} ({TIER_SCORES.get(tier, 0)} pts)"


class TierListVotingView(nextcord.ui.View):
    """Button-based voting UI (rebuilt on each state change with fresh rows)."""

    def __init__(
        self,
        *,
        list_id: int,
        voter_id: int,
        creator_id: int,
        mode: str,
        options: List[Dict[str, Any]],
        cursor: int,
        voted_tier: Optional[str],
        cog: "TierList",
    ) -> None:
        super().__init__(timeout=3600.0)
        self.list_id = list_id
        self.voter_id = voter_id
        self.creator_id = creator_id
        self.mode = mode
        self.cog = cog
        self.options = options
        self.cursor = max(0, min(cursor, len(options) - 1)) if options else 0
        n = max(len(options), 1)
        i = self.cursor
        # Row 0: nav
        prev = nextcord.ui.Button(
            label="◀",
            style=nextcord.ButtonStyle.secondary,
            custom_id=f"tlv_{list_id}_prev",
            row=0,
            disabled=(i <= 0),
        )
        prev.callback = self._on_prev
        self.add_item(prev)

        counter = nextcord.ui.Button(
            label=f"{i + 1}/{n}",
            style=nextcord.ButtonStyle.secondary,
            custom_id=f"tlv_{list_id}_count",
            row=0,
            disabled=True,
        )
        self.add_item(counter)

        next_b = nextcord.ui.Button(
            label="▶",
            style=nextcord.ButtonStyle.secondary,
            custom_id=f"tlv_{list_id}_next",
            row=0,
            disabled=(i >= n - 1),
        )
        next_b.callback = self._on_next
        self.add_item(next_b)

        # Tiers: row 1 = S A B C D, row 2 = F, N/A, Done (labels must match TIER_SCORES keys)
        for label in ("S", "A", "B", "C", "D"):
            b = nextcord.ui.Button(
                label=_voting_tier_label(label),
                style=nextcord.ButtonStyle.primary,
                custom_id=f"tlv_{list_id}_t_{label}",
                row=1,
                disabled=bool(voted_tier and voted_tier == label),
            )
            b.callback = partial(self.cog._handle_voting_tier_click, self, label)  # type: ignore[assignment]
            self.add_item(b)

        f_btn = nextcord.ui.Button(
            label=_voting_tier_label("F"),
            style=nextcord.ButtonStyle.primary,
            custom_id=f"tlv_{list_id}_t_F",
            row=2,
            disabled=bool(voted_tier and voted_tier == "F"),
        )
        f_btn.callback = partial(self.cog._handle_voting_tier_click, self, "F")  # type: ignore[assignment]
        self.add_item(f_btn)

        na_btn = nextcord.ui.Button(
            label=_voting_tier_label("N/A"),
            style=nextcord.ButtonStyle.secondary,
            custom_id=f"tlv_{list_id}_t_NA",
            row=2,
            disabled=bool(voted_tier and voted_tier == "N/A"),
        )
        na_btn.callback = partial(self.cog._handle_voting_tier_click, self, "N/A")  # type: ignore[assignment]
        self.add_item(na_btn)

        done = nextcord.ui.Button(
            label="Done", style=nextcord.ButtonStyle.danger, custom_id=f"tlv_{list_id}_done", row=2
        )
        done.callback = self._on_done  # type: ignore[assignment]
        self.add_item(done)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if self.mode == "personal" and interaction.user.id != self.creator_id:
            await interaction.response.send_message("Only the tier list creator can vote on this one.", ephemeral=True)
            return False
        if interaction.user.id != self.voter_id:
            await interaction.response.send_message("This voting session belongs to someone else.", ephemeral=True)
            return False
        return True

    async def _on_prev(self, interaction: Interaction) -> None:
        await self._go_nav(interaction, -1)

    async def _on_next(self, interaction: Interaction) -> None:
        await self._go_nav(interaction, 1)

    async def _go_nav(self, interaction: Interaction, delta: int) -> None:
        n = len(self.options)
        if n == 0:
            await interaction.response.defer()
            return
        self.cursor = clamp_int(self.cursor + delta, 0, n - 1)
        op = self.options[self.cursor]
        voted = await self.cog.get_user_tier_for_option(
            list_id=self.list_id, user_id=self.voter_id, option_id=int(op["option_id"])
        )
        embed, file, view = await self.cog.build_voting_interaction_state(
            list_id=self.list_id,
            voter_id=self.voter_id,
            creator_id=self.creator_id,
            mode=self.mode,
            options=self.options,
            cursor=self.cursor,
            voted_tier=voted,
        )
        kwargs: Dict[str, Any] = {"embed": embed, "view": view}
        if file is not None:
            kwargs["file"] = file
        await interaction.response.edit_message(**kwargs)

    async def _on_done(self, interaction: Interaction) -> None:
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class TierList(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None
        self._main_refresh_tasks: Dict[int, asyncio.Task] = {}

        self.bot.loop.create_task(self.add_persistent_views())
        self.auto_finish_expired.start()
        self.item_cache_sweep.start()

    async def cog_unload(self) -> None:
        try:
            self.auto_finish_expired.cancel()
        except Exception:
            pass
        try:
            self.item_cache_sweep.cancel()
        except Exception:
            pass
        for t in list(self._main_refresh_tasks.values()):
            t.cancel()
        if self._session:
            await self._session.close()

    async def cog_load(self) -> None:
        await self.create_tables()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession()
        return self._session

    async def create_tables(self) -> None:
        return

    @tasks.loop(hours=24)
    async def item_cache_sweep(self) -> None:
        await self.bot.wait_until_ready()
        if not os.path.isdir(FINAL_SUBDIR):
            return
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        max_age = 14 * 86400
        for name in os.listdir(FINAL_SUBDIR):
            fpath = os.path.join(FINAL_SUBDIR, name, "final_tierlist.png")
            if not os.path.isfile(fpath):
                continue
            if now - os.path.getmtime(fpath) < max_age:
                continue
            i_dir = os.path.join(ITEMS_SUBDIR, name)
            if os.path.isdir(i_dir):
                try:
                    shutil.rmtree(i_dir, ignore_errors=True)
                    logger.info("tierlist item cache removed for list_id=%s (final older than 14d)", name)
                except Exception:
                    logger.exception("item_cache_sweep failed for %s", i_dir)

    @item_cache_sweep.before_loop
    async def _before_item_sweep(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=60)
    async def auto_finish_expired(self) -> None:
        await self.bot.wait_until_ready()
        now = datetime.datetime.now(datetime.timezone.utc)
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f"""
                SELECT list_id FROM "{_TL}".tier_lists
                WHERE status = 'active' AND expires_at <= $1
                """,
                now.isoformat(),
            )
        for r in rows:
            try:
                await self.finish_tierlist(list_id=int(r["list_id"]), finished_by_user_id=None)
            except Exception:
                logger.exception("Auto-finish failed for list_id=%s", r["list_id"])

    @auto_finish_expired.before_loop
    async def _before_auto_finish(self) -> None:
        await self.bot.wait_until_ready()

    @nextcord.slash_command(name="tierlist", description="Create a tier list", guild_ids=[GUILD_ID])
    async def tierlist(self, interaction: Interaction) -> None:
        await interaction.response.send_message(
            "Use `/tierlist create` or `/tierlist show`.", ephemeral=True
        )

    @tierlist.subcommand(name="create", description="Create a tier list")
    async def tierlist_create(self, interaction: Interaction) -> None:
        v = TierListCreateVotingView(cog=self, user_id=interaction.user.id)
        await interaction.response.send_message(
            "Who will be voting on this? The whole server or just you?",
            view=v,
            ephemeral=True,
        )

    @tierlist.subcommand(
        name="show",
        description="Post a finished tier list image (one-time; does not edit the live list message)",
    )
    async def tierlist_show(
        self,
        interaction: Interaction,
        tierlist: str = SlashOption(
            name="tierlist",
            description="Pick a finished list (type to filter by title, date, or id)",
            autocomplete=True,
            required=True,
        ),
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        try:
            list_id = int(str(tierlist).strip())
        except ValueError:
            await interaction.response.send_message("Invalid tier list selection.", ephemeral=True)
            return

        await interaction.response.defer()
        async with self.bot.pg_pool.acquire() as db:
            row = await db.fetchrow(
                f"""
                SELECT * FROM "{_TL}".tier_lists
                WHERE list_id = $1 AND guild_id = $2 AND status = 'finished'
                """,
                list_id,
                interaction.guild.id,
            )
        if not row:
            await interaction.followup.send(
                "That tier list was not found, is still active, or belongs to another server.",
                ephemeral=True,
            )
            return

        path = _final_png_path(list_id)
        if not os.path.isfile(path):
            t_map, _ = await self._build_sorted_tier_map(list_id)
            os.makedirs(_final_dir(list_id), exist_ok=True)
            try:
                generate_tierlist_image(
                    output_path=path,
                    tier_to_items=t_map,
                    title=f"Final: {row['list_title']}",
                    subtitle=_tierlist_image_subtitle(list_status="finished", n_votes=None),
                )
            except Exception:
                logger.exception("Regenerate final tierlist for show failed list_id=%s", list_id)
                await interaction.followup.send("Could not build that tier list image.", ephemeral=True)
                return

        label = _tierlist_show_choice_label(str(row["created_at"]), str(row["list_title"]))
        emb = nextcord.Embed(
            title=f"Tier list: {row['list_title']}",
            description=label,
            color=nextcord.Color.blurple(),
        )
        emb.set_footer(text=f"List ID: {list_id} · /tierlist show")
        emb.set_image(url="attachment://final_tierlist.png")
        file = nextcord.File(path, filename="final_tierlist.png")
        await interaction.followup.send(embed=emb, file=file)

    @tierlist_show.on_autocomplete("tierlist")
    async def tierlist_show_autocomplete(self, interaction: Interaction, current: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_autocomplete([])
            return
        try:
            choices = await self._tierlist_show_autocomplete_choices(interaction.guild.id, current)
            await interaction.response.send_autocomplete(choices)
        except Exception:
            logger.exception("tierlist show autocomplete failed")
            if not interaction.response.is_done():
                await interaction.response.send_autocomplete([])

    async def _tierlist_show_autocomplete_choices(self, guild_id: int, current: str) -> Dict[str, str]:
        cur = (current or "").strip().lower()
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f"""
                SELECT list_id, list_title, created_at
                FROM "{_TL}".tier_lists
                WHERE guild_id = $1 AND status = 'finished'
                ORDER BY created_at DESC
                LIMIT 200
                """,
                guild_id,
            )
        acc: List[Tuple[str, str]] = []
        for r in rows:
            label = _tierlist_show_choice_label(str(r["created_at"]), str(r["list_title"]))
            lid = str(int(r["list_id"]))
            if cur and cur not in label.lower() and cur not in str(r["list_title"]).lower() and cur not in lid:
                continue
            acc.append((label, lid))
            if len(acc) >= 25:
                break
        acc.reverse()
        return _unique_autocomplete_dict(acc)

    async def create_tierlist_from_modal(
        self,
        *,
        interaction: Interaction,
        title: str,
        mode: str,
        duration_hours: int,
        options: List[str],
        image_search_prefix: Optional[str] = None,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        expires = now + datetime.timedelta(hours=duration_hours)

        async with self.bot.pg_pool.acquire() as db:
            async with db.transaction():
                list_id = await db.fetchval(
                    f"""
                    INSERT INTO "{_TL}".tier_lists
                        (guild_id, creator_id, list_title, list_mode, status, duration_hours, created_at, expires_at)
                    VALUES ($1, $2, $3, $4, 'active', $5, $6, $7)
                    RETURNING list_id
                    """,
                    interaction.guild_id or 0,
                    interaction.user.id,
                    title,
                    mode,
                    duration_hours,
                    now.isoformat(),
                    expires.isoformat(),
                )

                for idx, opt in enumerate(options):
                    await db.fetchval(
                        f"""
                        INSERT INTO "{_TL}".tier_options (list_id, option_text, option_index)
                        VALUES ($1, $2, $3)
                        RETURNING option_id
                        """,
                        list_id,
                        opt,
                        idx,
                    )

        option_rows = await self._load_option_dicts(int(list_id))
        if not option_rows or not interaction.channel:
            await interaction.followup.send(
                "List created, but the image picker could not be opened in this context.", ephemeral=True
            )
            return

        pview = TierListOptionImageView(
            cog=self,
            list_id=int(list_id),
            list_title=title,
            user_id=interaction.user.id,
            channel_id=interaction.channel.id,
            options=option_rows,
            flow="create",
            image_search_prefix=image_search_prefix,
        )
        warn = await pview._ensure_rows_for_option()
        pview._warn = warn
        emb, att = await pview.build_embed_and_file()
        try:
            send_kw: Dict[str, Any] = {"embed": emb, "view": pview, "ephemeral": True}
            if att is not None:
                send_kw["file"] = att
            sent = await interaction.followup.send(**send_kw)
            mid = getattr(sent, "id", None)
            if mid is not None:
                pview._picker_message_id = int(mid)
        except Exception:
            logger.exception("Could not start tier list image setup list_id=%s", list_id)
            await interaction.followup.send("Could not open the image selection UI. Try **Settings** on the list later.", ephemeral=True)

    async def _fetch_images_for_list(self, *, list_id: int, title: str) -> int:
        """Returns count of options that received a local image file."""
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f"""
                SELECT option_id, option_text FROM "{_TL}".tier_options
                WHERE list_id = $1 ORDER BY option_index ASC
                """,
                list_id,
            )

        session = await self._get_session()
        sem = asyncio.Semaphore(3)
        n_ok = 0

        async def process_one(r: Any) -> None:
            nonlocal n_ok
            async with sem:
                opt_id = int(r["option_id"])
                opt_text = str(r["option_text"])
                try:
                    out_path = os.path.join(_item_dir(list_id), f"{opt_id}.jpg")
                    used_url = await search_and_save_brave_option_image(
                        session,
                        title,
                        opt_text,
                        output_path=out_path,
                        search_query=tierlist_option_image_search_query(opt_text),
                    )
                    if not used_url:
                        return
                    async with self.bot.pg_pool.acquire() as db2:
                        await db2.execute(
                            f"""
                            UPDATE "{_TL}".tier_options SET image_url = $1, local_image_path = $2
                            WHERE option_id = $3
                            """,
                            used_url,
                            out_path,
                            opt_id,
                        )
                    n_ok += 1
                except BraveImageError:
                    return
                except Exception:
                    return

        await asyncio.gather(*[process_one(r) for r in rows])
        return n_ok

    async def _finalize_tierlist_after_image_wizard(
        self,
        interaction: Interaction,
        *,
        list_id: int,
        channel_id: int,
        view_to_stop: "TierListOptionImageView",
    ) -> None:
        """Build live image, post the public list message, store ids; called after the image picker flow."""
        async with self.bot.pg_pool.acquire() as db:
            row = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', int(list_id))
        if not row:
            view_to_stop.stop()
            return

        live_path = _live_png_path(int(list_id))
        try:
            t_map, n_votes = await self._build_sorted_tier_map(int(list_id))
            title_t = str(row["list_title"])
            generate_tierlist_image(
                output_path=live_path,
                tier_to_items=t_map,
                title=title_t,
                subtitle=_tierlist_image_subtitle(list_status=str(row.get("status", "active")), n_votes=n_votes),
            )
        except Exception:
            logger.exception("Post-wizard live image failed for list_id=%s", list_id)

        channel: Optional[Any] = self.bot.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            for ch in view_to_stop.children:
                if isinstance(ch, nextcord.ui.Button):
                    ch.disabled = True
            em = nextcord.Embed(
                title="List saved, channel missing",
                description="I could not find the channel to post the list. Use an admin to fix or repost.",
                color=nextcord.Color.orange(),
            )
            try:
                await _edit_tierlist_picker_message(
                    interaction,
                    embed=em,
                    file=None,
                    view=view_to_stop,
                    message_id=view_to_stop._picker_message_id,
                )
            except Exception:
                pass
            view_to_stop.stop()
            return

        embed, main_file = await self._build_main_message_payload(list_id=int(list_id), include_image=True)
        creator_id = int(row["creator_id"])
        main_view = TierListMainView(list_id=int(list_id), creator_id=creator_id, cog=self)
        send_kw: Dict[str, Any] = {"embed": embed, "view": main_view}
        if main_file is not None:
            send_kw["file"] = main_file
        try:
            msg = await channel.send(**send_kw)  # type: ignore[misc]
        except Exception as e:
            try:
                await interaction.followup.send(f"Failed to post the list: {e}", ephemeral=True)
            except Exception:
                pass
            view_to_stop.stop()
            return

        async with self.bot.pg_pool.acquire() as db:
            await db.execute(
                f"""
                UPDATE "{_TL}".tier_lists SET message_id = $1, channel_id = $2 WHERE list_id = $3
                """,
                int(msg.id),
                int(msg.channel.id),
                int(list_id),
            )
        self.bot.add_view(main_view)
        for ch in view_to_stop.children:
            if isinstance(ch, nextcord.ui.Button):
                ch.disabled = True
        done = nextcord.Embed(
            title="Tier list is live",
            description=f"Public message: {msg.jump_url}",
            color=nextcord.Color.green(),
        )
        try:
            await _edit_tierlist_picker_message(
                interaction,
                embed=done,
                file=None,
                view=None,
                message_id=view_to_stop._picker_message_id,
            )
        except Exception:
            pass
        view_to_stop.stop()
        try:
            await interaction.followup.send("Tierlist created; Photos selected.", ephemeral=True)
        except Exception:
            pass

    async def _build_main_message_payload(
        self, *, list_id: int, include_image: bool
    ) -> Tuple[nextcord.Embed, Optional[nextcord.File]]:
        async with self.bot.pg_pool.acquire() as db:
            row = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id)
            if not row:
                raise TierListError("Tier list not found")
            options_count = await db.fetchrow(
                f'SELECT COUNT(*) AS c FROM "{_TL}".tier_options WHERE list_id = $1',
                list_id,
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
        main_file: Optional[nextcord.File] = None
        if include_image and row["status"] == "active":
            p = _live_png_path(list_id)
            if os.path.isfile(p):
                embed.set_image(url=f"attachment://{LIVE_IMAGE_FILENAME}")
                main_file = nextcord.File(p, filename=LIVE_IMAGE_FILENAME)
        return embed, main_file

    async def add_persistent_views(self) -> None:
        """Re-register button handlers only; does not edit messages or regenerate tierlist images."""
        await self.bot.wait_until_ready()
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f'SELECT list_id, creator_id FROM "{_TL}".tier_lists WHERE status = \'active\''
            )
        for r in rows:
            try:
                view = TierListMainView(list_id=int(r["list_id"]), creator_id=int(r["creator_id"]), cog=self)
                self.bot.add_view(view)
            except Exception:
                logger.exception("Failed to add persistent view for list_id=%s", r["list_id"])

    async def handle_settings_button(self, interaction: Interaction, list_id: int) -> None:
        if interaction.user.id not in set(admin_user_ids or []):
            await interaction.response.send_message("You need admin access to use these settings.", ephemeral=True)
            return
        async with self.bot.pg_pool.acquire() as db:
            tl = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id)
        if not tl or str(tl["status"]) != "active":
            await interaction.response.send_message("Tier list not found or not active.", ephemeral=True)
            return
        option_rows = await self._load_option_dicts(int(list_id))
        if not option_rows:
            await interaction.response.send_message("This list has no options to edit.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        pview = TierListOptionImageView(
            cog=self,
            list_id=int(list_id),
            list_title=str(tl["list_title"]),
            user_id=interaction.user.id,
            channel_id=interaction.channel_id or 0,
            options=option_rows,
            flow="settings",
        )
        warn = await pview._ensure_rows_for_option()
        pview._warn = warn
        emb, att = await pview.build_embed_and_file()
        try:
            send_kw: Dict[str, Any] = {"embed": emb, "view": pview, "ephemeral": True}
            if att is not None:
                send_kw["file"] = att
            sent = await interaction.followup.send(**send_kw)
            mid = getattr(sent, "id", None)
            if mid is not None:
                pview._picker_message_id = int(mid)
        except Exception as e:
            logger.exception("Settings image UI failed: %s", e)
            await interaction.followup.send("Could not open the image settings UI. Try again.", ephemeral=True)

    async def handle_vote_button(self, interaction: Interaction, list_id: int) -> None:
        async with self.bot.pg_pool.acquire() as db:
            tl = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id)
            if not tl:
                await interaction.response.send_message("Tier list not found.", ephemeral=True)
                return
            if tl["status"] != "active":
                await interaction.response.send_message("This tier list is finished.", ephemeral=True)
                return
            creator_id = int(tl["creator_id"])
            mode = str(tl["list_mode"])

        options = await self._load_option_dicts(list_id)
        if not options:
            await interaction.response.send_message("This tier list has no options.", ephemeral=True)
            return

        first_un: Optional[int] = None
        for i, o in enumerate(options):
            v = await self.get_user_tier_for_option(
                list_id=list_id, user_id=interaction.user.id, option_id=int(o["option_id"])
            )
            if v is None:
                first_un = i
                break
        cursor = first_un if first_un is not None else 0
        op0 = options[cursor]
        voted = await self.get_user_tier_for_option(
            list_id=list_id, user_id=interaction.user.id, option_id=int(op0["option_id"])
        )

        embed, file, view = await self.build_voting_interaction_state(
            list_id=list_id,
            voter_id=interaction.user.id,
            creator_id=creator_id,
            mode=mode,
            options=options,
            cursor=cursor,
            voted_tier=voted,
        )
        ephemeral = mode == "server"
        send_kw: Dict[str, Any] = {"embed": embed, "view": view}
        if file is not None:
            send_kw["file"] = file
        if ephemeral:
            try:
                await interaction.response.send_message(**send_kw, ephemeral=True)
            except (nextcord.HTTPException, nextcord.DiscordException) as e:
                logger.warning("Ephemeral vote UI failed, trying DM: %s", e)
                try:
                    if interaction.user.dm_channel is None:
                        await interaction.user.create_dm()
                    await interaction.user.send(**send_kw)
                    if not interaction.response.is_done():
                        await interaction.response.send_message("Open your DMs for the voting UI.", ephemeral=True)
                except Exception as e2:
                    logger.exception("DM fallback failed: %s", e2)
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "Could not start voting. Enable DMs from server members and try again.",
                            ephemeral=True,
                        )
        else:
            await interaction.response.send_message(**send_kw, ephemeral=False)

    async def _load_option_dicts(self, list_id: int) -> List[Dict[str, Any]]:
        async with self.bot.pg_pool.acquire() as db:
            rows = await db.fetch(
                f"""
                SELECT option_id, option_text, local_image_path, option_index
                FROM "{_TL}".tier_options
                WHERE list_id = $1
                ORDER BY option_index ASC
                """,
                list_id,
            )
        return [dict(r) for r in rows]

    async def get_user_tier_for_option(
        self, *, list_id: int, user_id: int, option_id: int
    ) -> Optional[str]:
        async with self.bot.pg_pool.acquire() as db:
            r = await db.fetchrow(
                f"""
                SELECT tier_rank FROM "{_TL}".tier_votes
                WHERE list_id = $1 AND user_id = $2 AND option_id = $3
                """,
                list_id,
                user_id,
                option_id,
            )
        if not r:
            return None
        return str(r["tier_rank"])

    async def build_voting_interaction_state(
        self,
        *,
        list_id: int,
        voter_id: int,
        creator_id: int,
        mode: str,
        options: List[Dict[str, Any]],
        cursor: int,
        voted_tier: Optional[str],
    ) -> Tuple[nextcord.Embed, Optional[nextcord.File], TierListVotingView]:
        embed = await self._build_voting_embed(
            list_id=list_id,
            voter_id=voter_id,
            option_row=options[cursor] if options else None,
            progress_idx=cursor,
            n_options=len(options),
        )
        f: Optional[nextcord.File] = None
        orow = options[cursor] if options else None
        if orow and orow.get("local_image_path") and os.path.isfile(str(orow["local_image_path"])):
            embed.set_image(url=f"attachment://{VOTE_ITEM_FILENAME}")
            f = nextcord.File(str(orow["local_image_path"]), filename=VOTE_ITEM_FILENAME)
        view = TierListVotingView(
            list_id=list_id,
            voter_id=voter_id,
            creator_id=creator_id,
            mode=mode,
            options=options,
            cursor=cursor,
            voted_tier=voted_tier,
            cog=self,
        )
        return embed, f, view

    async def _build_voting_embed(
        self,
        *,
        list_id: int,
        voter_id: int,
        option_row: Optional[Dict[str, Any]],
        progress_idx: int,
        n_options: int,
    ) -> nextcord.Embed:
        async with self.bot.pg_pool.acquire() as db:
            tl = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id)
            if not tl:
                raise TierListError("Tier list not found")
            vote_ct = await db.fetchval(
                f"""SELECT COUNT(*) FROM "{_TL}".tier_votes WHERE list_id = $1 AND user_id = $2""", list_id, voter_id
            )

        v_text = f"{int(vote_ct)}/{n_options} options" if n_options else "0/0"
        if option_row is None:
            desc = f"Your progress: **{v_text}**."
        else:
            desc = (
                f"Progress: **{v_text}**.\n"
                f"# **{progress_idx + 1}/{n_options}** — **{option_row['option_text']}**\n\n"
                "◀/▶ to move through options."
            )
        embed = nextcord.Embed(
            title=f"Voting: {tl['list_title']}",
            description=desc,
            color=nextcord.Color.green(),
        )
        embed.set_footer(text=f"List ID: {list_id}")
        return embed

    def schedule_main_tierlist_refresh(self, list_id: int) -> None:
        old = self._main_refresh_tasks.get(list_id)
        if old and not old.done():
            old.cancel()
        self._main_refresh_tasks[list_id] = asyncio.create_task(self._debounced_main_refresh(list_id))

    async def _debounced_main_refresh(self, list_id: int) -> None:
        try:
            await asyncio.sleep(1.5)
            await self._refresh_main_tierlist_message(list_id)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Main tierlist refresh failed for list_id=%s", list_id)
        finally:
            self._main_refresh_tasks.pop(list_id, None)

    async def _refresh_main_tierlist_message(self, list_id: int) -> None:
        async with self.bot.pg_pool.acquire() as db:
            row = await db.fetchrow(
                f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id
            )
        if not row or row["status"] != "active" or not row.get("message_id") or not row.get("channel_id"):
            return
        ch = self.bot.get_channel(int(row["channel_id"]))
        if ch is None:
            return
        try:
            msg = await ch.fetch_message(int(row["message_id"]))
        except Exception:
            return
        t_map, n_votes = await self._build_sorted_tier_map(list_id)
        title = str(row["list_title"])
        out = _live_png_path(list_id)
        try:
            generate_tierlist_image(
                output_path=out,
                tier_to_items=t_map,
                title=title,
                subtitle=_tierlist_image_subtitle(list_status=str(row.get("status", "active")), n_votes=n_votes),
            )
        except Exception:
            logger.exception("Live image regen failed list_id=%s", list_id)
            return
        embed, f = await self._build_main_message_payload(list_id=list_id, include_image=True)
        view = TierListMainView(
            list_id=list_id, creator_id=int(row["creator_id"]), cog=self
        )
        try:
            await msg.edit(
                embed=embed,
                file=f,
                view=view,
            )
            self.bot.add_view(view)
        except Exception:
            logger.exception("Could not edit main tierlist message list_id=%s", list_id)

    async def _build_sorted_tier_map(self, list_id: int) -> Tuple[Dict[str, List[Dict[str, Any]]], int]:
        tier_to: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TIER_ORDER}
        total_cast = 0
        async with self.bot.pg_pool.acquire() as db:
            options = await db.fetch(
                f"""
                SELECT option_id, option_text, local_image_path, option_index
                FROM "{_TL}".tier_options
                WHERE list_id = $1
                ORDER BY option_index ASC
                """,
                list_id,
            )
            for opt in options:
                votes = await db.fetch(
                    f"""
                    SELECT tier_score FROM "{_TL}".tier_votes
                    WHERE list_id = $1 AND option_id = $2
                    """,
                    list_id,
                    opt["option_id"],
                )
                total_cast += len(votes)
                if not votes:
                    final_tier = "N/A"
                    it = {
                        "text": str(opt["option_text"]),
                        "image_path": opt.get("local_image_path"),
                        "avg": None,
                        "vote_count": 0,
                    }
                else:
                    avg = sum(int(v["tier_score"]) for v in votes) / len(votes)
                    sc = int(round(avg))
                    sc = clamp_int(sc, -1, 5)
                    final_tier = SCORE_TO_TIER.get(sc, "N/A")
                    it = {
                        "text": str(opt["option_text"]),
                        "image_path": opt.get("local_image_path"),
                        "avg": float(avg),
                        "vote_count": len(votes),
                    }
                tier_to[final_tier].append(it)
        def _sort_key(d: Dict[str, Any]) -> tuple:
            a = d.get("avg")
            if a is None:
                return (1, 0.0)
            return (0, -float(a))

        for t in TIER_ORDER:
            tier_to[t].sort(key=_sort_key)

        async with self.bot.pg_pool.acquire() as db:
            c = await db.fetchval(
                f'SELECT COUNT(*) FROM "{_TL}".tier_votes WHERE list_id = $1', list_id
            )
        n_global = int(c) if c is not None else 0
        return tier_to, n_global

    async def _next_unvoted_index(self, list_id: int, user_id: int, from_idx: int) -> int:
        options = await self._load_option_dicts(list_id)
        n = len(options)
        if n == 0:
            return 0
        for step in range(1, n + 1):
            idx = (from_idx + step) % n
            oid = int(options[idx]["option_id"])
            v = await self.get_user_tier_for_option(
                list_id=list_id, user_id=user_id, option_id=oid
            )
            if v is None:
                return idx
        return (from_idx + 1) % n

    async def _handle_voting_tier_click(
        self, view: TierListVotingView, tier: str, interaction: Interaction
    ) -> None:
        option_id = int(view.options[view.cursor]["option_id"])
        score = int(TIER_SCORES.get(tier, 0))
        list_id = view.list_id
        uid = view.voter_id
        await interaction.response.defer()
        async with self.bot.pg_pool.acquire() as db:
            await db.execute(
                f"""
                INSERT INTO "{_TL}".tier_votes (list_id, option_id, user_id, tier_rank, tier_score, voted_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (list_id, option_id, user_id) DO UPDATE SET
                    tier_rank = EXCLUDED.tier_rank,
                    tier_score = EXCLUDED.tier_score,
                    voted_at = EXCLUDED.voted_at
                """,
                list_id,
                option_id,
                uid,
                tier,
                score,
                utcnow_iso(),
            )
        self.schedule_main_tierlist_refresh(list_id)
        nxt = await self._next_unvoted_index(list_id, uid, view.cursor)
        op2 = view.options[nxt]
        v2 = await self.get_user_tier_for_option(
            list_id=list_id, user_id=uid, option_id=int(op2["option_id"])
        )
        embed, file, nview = await self.build_voting_interaction_state(
            list_id=list_id,
            voter_id=uid,
            creator_id=view.creator_id,
            mode=view.mode,
            options=view.options,
            cursor=nxt,
            voted_tier=v2,
        )
        kwargs2: Dict[str, Any] = {"embed": embed, "view": nview}
        if file is not None:
            kwargs2["file"] = file
        await interaction.edit_original_message(**kwargs2)

    async def handle_finish_button(self, interaction: Interaction, list_id: int) -> None:
        async with self.bot.pg_pool.acquire() as db:
            tl = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id)
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
        await self.finish_tierlist(
            list_id=list_id, finished_by_user_id=interaction.user.id, interaction=interaction
        )

    async def finish_tierlist(
        self,
        *,
        list_id: int,
        finished_by_user_id: Optional[int],
        interaction: Optional[Interaction] = None,
    ) -> None:
        async with self.bot.pg_pool.acquire() as db:
            tl = await db.fetchrow(f'SELECT * FROM "{_TL}".tier_lists WHERE list_id = $1', list_id)
            if not tl:
                return
            if tl["status"] != "active":
                return
            await db.execute(
                f'UPDATE "{_TL}".tier_lists SET status = \'finished\' WHERE list_id = $1', list_id
            )

        t_map, _n = await self._build_sorted_tier_map(list_id)
        out_dir = _final_dir(list_id)
        os.makedirs(out_dir, exist_ok=True)
        out_path = _final_png_path(list_id)
        generate_tierlist_image(
            output_path=out_path,
            tier_to_items=t_map,
            title=f"Final: {tl['list_title']}",
            subtitle=_tierlist_image_subtitle(list_status="finished", n_votes=None),
        )

        emb = nextcord.Embed(
            title=f"Final Tier List: {tl['list_title']}",
            description="Voting finished. Results below.",
            color=nextcord.Color.gold(),
        )
        file = nextcord.File(out_path, filename="final_tierlist.png")
        emb.set_image(url="attachment://final_tierlist.png")
        # Auto-expire (no interaction) must not channel.send: the tasks loop runs once at startup
        # and would post one message per expired list. Use `/tierlist show` to repost a snapshot.
        if interaction is not None:
            await interaction.followup.send(embed=emb, file=file)

        try:
            if tl["channel_id"] and tl["message_id"]:
                ch = self.bot.get_channel(int(tl["channel_id"]))
                if ch:
                    msg = await ch.fetch_message(int(tl["message_id"]))
                    em2, f2 = await self._build_main_message_payload(
                        list_id=list_id, include_image=False
                    )
                    em2.color = nextcord.Color.greyple()
                    em2.description = (em2.description or "") + "\n\n*Finished.*"
                    await msg.edit(
                        embed=em2,
                        view=None,
                    )
        except Exception:
            pass

def setup(bot: commands.Bot) -> None:
    bot.add_cog(TierList(bot))
