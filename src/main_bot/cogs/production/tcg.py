from __future__ import annotations

import asyncio
import re
import time

import aiohttp
import nextcord
import requests
from nextcord.ext import commands

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.guild_settings import get_settings, mtg_autolink_channel_ids
from main_bot.server_configs.config import GUILD_ID, MANA_SYMBOLS
from main_bot.utils.mtg_autolink import (
    distinct_span_phrases,
    greedy_resolve_cards,
    normalize_for_autocard_match,
    normalize_phrase,
    tokenize,
)


SCRYFALL_HEADERS = {
    "User-Agent": "DiscordBot (JJ3571, v0.1)",
    "Accept": "application/json",
}

# Minimum seconds between replies in channels listed by MTG_AUTOLINK_COOLDOWN_CHANNEL_IDS (not per-user).
MTG_AUTOLINK_COOLDOWN_SEC = 90

# Discord string selects accept at most 25 options.
_SELECT_MAX = 25

# Card and set menus stay valid after a restart: timeout is None, these ids
# never change, and TCG.register_persistent_views() registers one view for
# every lookup post. The chosen card, printing, and page are read off the message.
TCG_CARD_SELECT_ID = "tcg_card_select"
TCG_SET_SELECT_ID = "tcg_set_select"
TCG_SET_PREV_ID = "tcg_set_prev"
TCG_SET_NEXT_ID = "tcg_set_next"
_PRINTING_PAGE_RE = re.compile(r"Printings (\d+)-\d+ of (\d+)")


def card_select_options(names: list[str]) -> list[nextcord.SelectOption]:
    """Build card-name options. Values are the names the lookup will search."""
    options: list[nextcord.SelectOption] = []
    seen: set[str] = set()
    for name in names:
        value = str(name)[:100]
        if not value or value in seen:
            continue
        seen.add(value)
        options.append(nextcord.SelectOption(label=value, value=value))
        if len(options) >= _SELECT_MAX:
            break
    return options


def set_select_options(printings: list[dict]) -> list[nextcord.SelectOption]:
    """One option per printing. Callers page this list down to 25 before sending it."""
    options: list[nextcord.SelectOption] = []
    seen: set[str] = set()
    for printing in printings:
        value = str(printing.get("id") or "")[:100]
        if not value or value in seen:
            continue
        seen.add(value)
        label = str(printing.get("set_name") or "Unknown set")[:100]
        bits: list[str] = []
        code = printing.get("set")
        number = printing.get("collector_number")
        if code:
            bits.append(str(code).upper())
        if number:
            bits.append(f"#{number}")
        description = " ".join(bits)[:100] or None
        options.append(
            nextcord.SelectOption(label=label, value=value, description=description)
        )
    return options


def page_count(total: int) -> int:
    if total <= 0:
        return 1
    return (total + _SELECT_MAX - 1) // _SELECT_MAX


def page_containing(options: list[nextcord.SelectOption], value: str | None) -> int:
    if not value:
        return 0
    index = next((i for i, opt in enumerate(options) if opt.value == value), None)
    if index is None:
        return 0
    return index // _SELECT_MAX


def option_page(
    options: list[nextcord.SelectOption],
    page: int,
) -> tuple[list[nextcord.SelectOption], int, int]:
    """Return one Discord-sized page, clamped into range, plus the page count."""
    pages = page_count(len(options))
    if not options:
        return [], 0, 1
    current = min(max(page, 0), pages - 1)
    start = current * _SELECT_MAX
    return options[start : start + _SELECT_MAX], current, pages


def printing_footer(set_name: str, *, page: int, total: int) -> str:
    name = set_name or "Unknown set"
    if total <= _SELECT_MAX:
        return f"Set: {name}"
    start = page * _SELECT_MAX + 1
    end = min(total, (page + 1) * _SELECT_MAX)
    return f"Set: {name}\nPrintings {start}-{end} of {total}"


def page_state_from_footer(text: str | None) -> tuple[int, int]:
    """Page index and total printings. Total is 0 when the footer has no page line."""
    match = _PRINTING_PAGE_RE.search(text or "")
    if not match:
        return 0, 0
    start = int(match.group(1))
    total = int(match.group(2))
    return max(0, (start - 1) // _SELECT_MAX), total


def footer_text(embed: nextcord.Embed | None) -> str:
    if embed is None:
        return ""
    footer = getattr(embed, "footer", None)
    if footer is None:
        return ""
    return str(getattr(footer, "text", "") or "")


def with_selection(
    options: list[nextcord.SelectOption],
    selected: str | None,
) -> list[nextcord.SelectOption]:
    """Copy options and check the one the user picked."""
    marked: list[nextcord.SelectOption] = []
    for opt in options[:_SELECT_MAX]:
        marked.append(
            nextcord.SelectOption(
                label=opt.label[:100],
                value=(opt.value or opt.label)[:100],
                description=opt.description[:100] if opt.description else None,
                emoji=opt.emoji,
                default=selected is not None and opt.value == selected,
            )
        )
    return marked


def chosen_value(options: list[nextcord.SelectOption]) -> str | None:
    for opt in options:
        if opt.default:
            return opt.value
    return None


def remembered_card(options: list[nextcord.SelectOption], title: str | None) -> str | None:
    """Keep the card checkmark from the menu, or from the embed title if Discord omitted it."""
    picked = chosen_value(options)
    if picked:
        return picked
    if not title:
        return None
    for opt in options:
        if opt.value == title or opt.label == title:
            return opt.value
    return None


def selected_from_interaction(interaction: nextcord.Interaction) -> str | None:
    """Read the click payload. The registered view is shared, so do not use ``Select.values``."""
    data = interaction.data or {}
    values = data.get("values") or []
    if not values:
        return None
    return str(values[0])


def options_from_message(
    message: nextcord.Message | None,
    custom_id: str,
) -> list[nextcord.SelectOption]:
    """Read the options Discord already stored on this post."""
    if message is None:
        return []
    for row in message.components or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) != custom_id:
                continue
            copied: list[nextcord.SelectOption] = []
            for opt in getattr(child, "options", []) or []:
                copied.append(
                    nextcord.SelectOption(
                        label=opt.label,
                        value=opt.value,
                        description=getattr(opt, "description", None),
                        emoji=getattr(opt, "emoji", None),
                        default=bool(getattr(opt, "default", False)),
                    )
                )
            return copied
    return []


def lookup_view(
    cog: TCG,
    *,
    card_options: list[nextcord.SelectOption] | None = None,
    selected_card: str | None = None,
    set_options: list[nextcord.SelectOption] | None = None,
    selected_set: str | None = None,
    page: int = 0,
    page_count: int = 1,
) -> TCGLookupView | None:
    if not card_options and not set_options:
        return None
    return TCGLookupView(
        cog,
        card_options=card_options,
        selected_card=selected_card,
        set_options=set_options,
        selected_set=selected_set,
        page=page,
        page_count=page_count,
    )


class TCGLookupView(nextcord.ui.View):
    """One view for every card lookup. ``prevent_update`` keeps clicks on the registered instance."""

    def __init__(
        self,
        cog: TCG,
        *,
        card_options: list[nextcord.SelectOption] | None = None,
        selected_card: str | None = None,
        set_options: list[nextcord.SelectOption] | None = None,
        selected_set: str | None = None,
        page: int = 0,
        page_count: int = 1,
    ):
        super().__init__(timeout=None, prevent_update=False)
        self.cog = cog
        if card_options:
            self.add_item(TCGCardSelect(card_options, selected=selected_card))
        if set_options:
            self.add_item(
                TCGSetSelect(
                    set_options,
                    selected=selected_set,
                    row=1 if card_options else 0,
                )
            )
        if set_options and page_count > 1:
            button_row = 2 if card_options else 1
            self.add_item(
                TCGSetPageButton(
                    custom_id=TCG_SET_PREV_ID,
                    label="Previous printings",
                    row=button_row,
                    disabled=page <= 0,
                )
            )
            self.add_item(
                TCGSetPageButton(
                    custom_id=TCG_SET_NEXT_ID,
                    label="Next printings",
                    row=button_row,
                    disabled=page >= page_count - 1,
                )
            )


class TCGCardSelect(nextcord.ui.Select):
    def __init__(self, options: list[nextcord.SelectOption], *, selected: str | None = None):
        marked = with_selection(options, selected)
        label = next((opt.label for opt in marked if opt.default), None)
        super().__init__(
            placeholder=(label or "Choose a card")[:150],
            min_values=1,
            max_values=1,
            options=marked,
            custom_id=TCG_CARD_SELECT_ID,
            row=0,
        )

    async def callback(self, interaction: nextcord.Interaction):
        card_name = selected_from_interaction(interaction)
        if not card_name:
            await interaction.response.send_message("Pick a card from the list.", ephemeral=True)
            return
        await self.view.cog.on_card_selected(interaction, card_name)


class TCGSetSelect(nextcord.ui.Select):
    def __init__(
        self,
        options: list[nextcord.SelectOption],
        *,
        selected: str | None = None,
        row: int = 1,
    ):
        marked = with_selection(options, selected)
        label = next((opt.label for opt in marked if opt.default), None)
        super().__init__(
            placeholder=(label or "Choose a set")[:150],
            min_values=1,
            max_values=1,
            options=marked,
            custom_id=TCG_SET_SELECT_ID,
            row=row,
        )

    async def callback(self, interaction: nextcord.Interaction):
        set_id = selected_from_interaction(interaction)
        if not set_id:
            await interaction.response.send_message("Pick a set from the list.", ephemeral=True)
            return
        await self.view.cog.on_set_selected(interaction, set_id)


class TCGSetPageButton(nextcord.ui.Button):
    def __init__(self, *, custom_id: str, label: str, row: int, disabled: bool = False):
        super().__init__(
            style=nextcord.ButtonStyle.secondary,
            label=label,
            custom_id=custom_id,
            disabled=disabled,
            row=row,
        )

    async def callback(self, interaction: nextcord.Interaction):
        raw = str((interaction.data or {}).get("custom_id") or "")
        delta = -1 if raw == TCG_SET_PREV_ID else 1
        await self.view.cog.on_set_page(interaction, delta)


class TCG(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        self._autolink_session: aiohttp.ClientSession | None = None
        self._mtg_autolink_last_sent_at: dict[int, float] = {}
        self._persistent_views: list[nextcord.ui.View] = []

    async def cog_load(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30)
        self._autolink_session = aiohttp.ClientSession(
            headers=SCRYFALL_HEADERS,
            timeout=timeout,
        )

    def cog_unload(self) -> None:
        # Nextcord calls cog_unload() synchronously (does not await); schedule aiohttp shutdown.
        self._remove_persistent_views()
        sess = self._autolink_session
        self._autolink_session = None
        if sess is not None and not sess.closed:
            try:
                self.bot.loop.create_task(sess.close())
            except RuntimeError:
                pass

    def register_persistent_views(self) -> None:
        """Keep card and set menus working across restarts.

        Discord only delivers a selection after a process restart when every
        menu has a stable ``custom_id``, ``timeout`` is ``None``, and the view
        is registered here. One view serves every lookup post. The chosen
        values are read from that message, not stored on this instance.
        """
        self._remove_persistent_views()
        view = TCGLookupView(
            self,
            card_options=[nextcord.SelectOption(label="Card", value="card")],
            set_options=[nextcord.SelectOption(label="Set", value="set")],
            page=0,
            page_count=2,
        )
        self._persistent_views = [view]
        self.bot.add_view(view)

    def _remove_persistent_views(self) -> None:
        for view in self._persistent_views:
            self.bot.remove_view(view)
        self._persistent_views = []

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message) -> None:
        channel_ids = mtg_autolink_channel_ids()
        if not channel_ids:
            return
        if message.author.bot:
            return
        if message.guild is None:
            return
        if isinstance(message.channel, nextcord.DMChannel):
            return

        ch_id = message.channel.id
        if ch_id not in channel_ids:
            return

        gs = get_settings()
        cooldown_ids = set(gs.get_int_list("mtg_autolink_cooldown_channel_ids"))
        cooldown_for_channel = bool(cooldown_ids) and ch_id in cooldown_ids
        if cooldown_for_channel:
            now = time.monotonic()
            last_at = self._mtg_autolink_last_sent_at.get(ch_id)
            if last_at is not None and (now - last_at) < MTG_AUTOLINK_COOLDOWN_SEC:
                return

        text = (message.content or "").strip()
        if not text:
            return

        tokens = tokenize(text)
        if not tokens:
            return

        phrases = distinct_span_phrases(
            tokens,
            gs.get_int("mtg_autolink_max_word_span"),
            frozenset(normalize_phrase(n) for n in gs.get_str_list("mtg_autolink_blocked_names")),
        )
        if not phrases:
            return

        session = self._autolink_session
        if not session:
            timeout = aiohttp.ClientTimeout(total=30)
            session = aiohttp.ClientSession(
                headers=SCRYFALL_HEADERS,
                timeout=timeout,
            )
            temporary_session = True
        else:
            temporary_session = False

        try:
            resolved = await self._scryfall_collection_named(session, phrases)
            if not resolved:
                return

            cards = greedy_resolve_cards(
                tokens,
                gs.get_int("mtg_autolink_max_word_span"),
                resolved,
                blocked_normalized=frozenset(
                    normalize_phrase(n) for n in gs.get_str_list("mtg_autolink_blocked_names")
                ),
                max_cards=gs.get_int("mtg_autolink_max_cards_per_message"),
            )
            if not cards:
                return

            for card in cards:
                embed = self.create_card_embed(card, art_as_thumbnail=True)
                try:
                    await message.reply(embed=embed, mention_author=False)
                except nextcord.Forbidden:
                    self.cog_print(
                        f"MTG autolink: missing permission to reply in channel {message.channel}"
                    )
                    return
                await asyncio.sleep(0.075)
            if cooldown_for_channel:
                self._mtg_autolink_last_sent_at[ch_id] = time.monotonic()
        finally:
            if temporary_session:
                await session.close()

    async def _scryfall_collection_named(
        self,
        session: aiohttp.ClientSession,
        phrases: list[str],
    ) -> dict:
        """Maps normalized card names (and comma-stripped aliases) to card JSON from Scryfall."""
        if not phrases:
            return {}

        result: dict = {}
        chunk_size = 375

        for start in range(0, len(phrases), chunk_size):
            chunk = phrases[start : start + chunk_size]
            payload = {"identifiers": [{"name": p} for p in chunk]}

            async with session.post(
                "https://api.scryfall.com/cards/collection",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:240]
                    self.cog_print(f"Scryfall /cards/collection HTTP {resp.status}: {body}")
                    continue

                data = await resp.json()
                for card in data.get("data", []):
                    k = normalize_phrase(card["name"])
                    result[k] = card
                    alt = normalize_for_autocard_match(card["name"])
                    if alt != k:
                        result.setdefault(alt, card)

                if start + chunk_size < len(phrases):
                    await asyncio.sleep(0.1)

        return result

    @nextcord.slash_command(name="mtg", description="Magic: The Gathering commands",guild_ids=[GUILD_ID])
    async def mtg(self, interaction: nextcord.Interaction):
        pass

    @mtg.subcommand(name="cardlookup", description="Look up a Magic: The Gathering card")
    async def mtg_cardlookup(self, interaction: nextcord.Interaction, card_name: str):
        await interaction.response.defer()
        suggestions = self.get_card_suggestions(card_name)
        if not suggestions:
            await interaction.followup.send(f"No cards found with the name '{card_name}'.")
            return

        if len(suggestions) == 1:
            await self.display_card_details(interaction, suggestions[0])
        else:
            options = card_select_options(suggestions)
            view = lookup_view(self, card_options=options)
            await interaction.followup.send("Select a card:", view=view)

    def get_card_suggestions(self, card_name):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json",
        }
        response = requests.get(
            f"https://api.scryfall.com/cards/autocomplete?q={card_name}", headers=headers
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        return None

    def _lookup_message(
        self,
        card: dict,
        *,
        printings: list[dict],
        card_options: list[nextcord.SelectOption] | None = None,
        selected_card: str | None = None,
        selected_set: str | None = None,
        page: int | None = None,
    ) -> tuple[nextcord.Embed, TCGLookupView | None]:
        """One embed plus the card menu, the set menu, and printing pages when needed."""
        all_sets = set_select_options(printings)
        if page is None:
            page = page_containing(all_sets, selected_set)
        page_options, page, pages = option_page(all_sets, page)
        embed = self.create_card_embed(card)
        embed.set_footer(
            text=printing_footer(
                str(card.get("set_name") or "Unknown set"),
                page=page,
                total=len(all_sets),
            )
        )
        view = lookup_view(
            self,
            card_options=card_options,
            selected_card=selected_card,
            set_options=page_options or None,
            selected_set=selected_set,
            page=page,
            page_count=pages,
        )
        return embed, view

    def _build_card_message(
        self,
        card_name: str,
        card_options: list[nextcord.SelectOption] | None = None,
    ) -> tuple[nextcord.Embed, TCGLookupView | None] | None:
        card = self.get_card_data(card_name)
        if not card:
            return None
        printings = self.get_card_sets(card) or []
        return self._lookup_message(
            card,
            printings=printings,
            card_options=card_options,
            selected_card=card_name if card_options else None,
            selected_set=card.get("id") if printings else None,
        )

    async def _edit_lookup(
        self,
        interaction: nextcord.Interaction,
        *,
        embed: nextcord.Embed,
        view: TCGLookupView | None,
    ) -> None:
        try:
            await interaction.edit_original_message(content=None, embed=embed, view=view)
        except nextcord.HTTPException as exc:
            self.cog_print(f"TCG lookup menu update failed: {exc}")
            await interaction.followup.send(
                "Couldn't update that card. Try the lookup again.",
                ephemeral=True,
            )

    async def display_card_details(self, interaction, card_name):
        if not interaction.response.is_done():
            await interaction.response.defer()

        built = self._build_card_message(card_name)
        if built is None:
            await interaction.followup.send(f"Could not retrieve details for '{card_name}'.")
            return

        embed, view = built
        await interaction.followup.send(embed=embed, view=view)

    async def on_card_selected(self, interaction: nextcord.Interaction, card_name: str) -> None:
        await interaction.response.defer()
        card_options = options_from_message(interaction.message, TCG_CARD_SELECT_ID)
        if not card_options:
            card_options = card_select_options([card_name])
        built = self._build_card_message(card_name, card_options=card_options)
        if built is None:
            await interaction.followup.send(
                f"Could not retrieve details for '{card_name}'.",
                ephemeral=True,
            )
            return
        embed, view = built
        await self._edit_lookup(interaction, embed=embed, view=view)

    async def on_set_selected(self, interaction: nextcord.Interaction, set_id: str) -> None:
        await interaction.response.defer()
        card = self.get_card_data_by_set(set_id)
        if not card:
            await interaction.followup.send(
                "Could not retrieve details for the selected set.",
                ephemeral=True,
            )
            return

        message = interaction.message
        embeds = list(message.embeds) if message is not None and message.embeds else []
        title = embeds[0].title if embeds else None
        card_options = options_from_message(message, TCG_CARD_SELECT_ID)
        catalog = self.get_card_data(card.get("name") or title or "") or card
        printings = self.get_card_sets(catalog) or [card]
        embed, view = self._lookup_message(
            card,
            printings=printings,
            card_options=card_options or None,
            selected_card=remembered_card(card_options, title or card.get("name")),
            selected_set=set_id,
        )
        await self._edit_lookup(interaction, embed=embed, view=view)

    async def on_set_page(self, interaction: nextcord.Interaction, delta: int) -> None:
        await interaction.response.defer()
        message = interaction.message
        embeds = list(message.embeds) if message is not None and message.embeds else []
        if not embeds or not embeds[0].title:
            await interaction.followup.send("Couldn't tell which card this is.", ephemeral=True)
            return

        title = embeds[0].title
        card_options = options_from_message(message, TCG_CARD_SELECT_ID)
        set_options = options_from_message(message, TCG_SET_SELECT_ID)
        selected_set = chosen_value(set_options)
        page, _total = page_state_from_footer(footer_text(embeds[0]))
        named = self.get_card_data(title)
        if not named:
            await interaction.followup.send(
                "Couldn't refresh printings for that card.",
                ephemeral=True,
            )
            return
        printings = self.get_card_sets(named) or []
        shown = self.get_card_data_by_set(selected_set) if selected_set else None
        embed, view = self._lookup_message(
            shown or named,
            printings=printings,
            card_options=card_options or None,
            selected_card=remembered_card(card_options, title),
            selected_set=selected_set,
            page=page + delta,
        )
        await self._edit_lookup(interaction, embed=embed, view=view)

    def get_card_data(self, card_name):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json",
        }
        response = requests.get(
            f"https://api.scryfall.com/cards/named?exact={card_name}", headers=headers
        )
        if response.status_code == 200:
            return response.json()
        return None

    def get_card_sets(self, card):
        url = card.get("prints_search_uri") if isinstance(card, dict) else None
        if not url:
            return []
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json",
        }
        printings: list[dict] = []
        for _ in range(6):
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                break
            data = response.json()
            printings.extend(data.get("data") or [])
            url = data.get("next_page") if data.get("has_more") else None
            if not url:
                break
            time.sleep(0.1)
        return printings

    def create_card_embed(self, card, *, art_as_thumbnail: bool = False):
        embed = nextcord.Embed(
            title=card["name"],
            description=self.format_mana(card.get("oracle_text", "No description")),
            color=0x00FF00,
        )

        face_uris = card.get("image_uris") or {}
        border_crop = face_uris.get("border_crop")
        if not border_crop:
            faces = card.get("card_faces") or []
            if faces:
                fu = faces[0].get("image_uris") or {}
                border_crop = fu.get("border_crop")
        if border_crop:
            if art_as_thumbnail:
                embed.set_thumbnail(url=border_crop)
            else:
                embed.set_image(url=border_crop)

        embed.add_field(
            name="Mana Cost",
            value=self.format_mana(card.get("mana_cost")),
            inline=True,
        )
        embed.add_field(name="Type", value=card["type_line"], inline=True)
        if "power" in card and "toughness" in card:
            embed.add_field(
                name="Power/Toughness",
                value=f"{card['power']}/{card['toughness']}",
                inline=True,
            )
        embed.set_footer(text=f"Set: {card['set_name']}")
        return embed

    def get_card_data_by_set(self, set_id):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json",
        }
        response = requests.get(f"https://api.scryfall.com/cards/{set_id}", headers=headers)
        if response.status_code == 200:
            return response.json()
        return None

    def format_mana(self, text):
        if text is None:
            return "None"
        text = str(text).strip()
        if not text:
            return "None"

        def replace_symbol(match):
            symbol = match.group(1)
            if symbol in MANA_SYMBOLS:
                # JSON/env MANA_SYMBOLS values must be strings for re.sub; coerce numbers etc.
                return str(MANA_SYMBOLS[symbol])
            return match.group(0)

        return re.sub(r"\{(.*?)\}", replace_symbol, text)


def setup(bot):
    cog = TCG(bot)
    bot.add_cog(cog)
    cog.register_persistent_views()
    boot_print("TCGCog has been added to the bot.")
