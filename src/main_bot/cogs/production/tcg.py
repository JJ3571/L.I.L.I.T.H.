import asyncio
import re
import time

import aiohttp
import nextcord
import requests
from nextcord.ext import commands

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import (
    GUILD_ID,
    MANA_SYMBOLS,
    mtg_autolink_blocked_names,
    mtg_autolink_channel_ids,
    mtg_autolink_cooldown_channel_ids,
    mtg_autolink_max_cards_per_message,
    mtg_autolink_max_word_span,
)
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


class TCG(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot
        self._autolink_session: aiohttp.ClientSession | None = None
        self._mtg_autolink_last_sent_at: dict[int, float] = {}

    async def cog_load(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30)
        self._autolink_session = aiohttp.ClientSession(
            headers=SCRYFALL_HEADERS,
            timeout=timeout,
        )

    def cog_unload(self) -> None:
        # Nextcord calls cog_unload() synchronously (does not await); schedule aiohttp shutdown.
        sess = self._autolink_session
        self._autolink_session = None
        if sess is not None and not sess.closed:
            try:
                self.bot.loop.create_task(sess.close())
            except RuntimeError:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message) -> None:
        if not mtg_autolink_channel_ids:
            return
        if message.author.bot:
            return
        if message.guild is None:
            return
        if isinstance(message.channel, nextcord.DMChannel):
            return

        ch_id = message.channel.id
        if ch_id not in mtg_autolink_channel_ids:
            return

        cooldown_for_channel = (
            bool(mtg_autolink_cooldown_channel_ids)
            and ch_id in mtg_autolink_cooldown_channel_ids
        )
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
            mtg_autolink_max_word_span,
            mtg_autolink_blocked_names,
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
                mtg_autolink_max_word_span,
                resolved,
                blocked_normalized=mtg_autolink_blocked_names,
                max_cards=mtg_autolink_max_cards_per_message,
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
            await self.present_suggestions(interaction, suggestions)

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

    async def present_suggestions(self, interaction, suggestions):
        options = [nextcord.SelectOption(label=suggestion) for suggestion in suggestions]
        select = nextcord.ui.Select(placeholder="Choose a card", options=options)

        async def select_callback(interaction):
            await self.display_card_details(interaction, select.values[0])

        select.callback = select_callback
        view = nextcord.ui.View()
        view.add_item(select)
        await interaction.followup.send("Select a card:", view=view)

    async def display_card_details(self, interaction, card_name):
        card = self.get_card_data(card_name)
        if not card:
            await interaction.followup.send(f"Could not retrieve details for '{card_name}'.")
            return

        embed = self.create_card_embed(card)

        if not interaction.response.is_done():
            await interaction.response.defer()

        original_message = await interaction.followup.send(embed=embed)

        sets = self.get_card_sets(card)
        if sets:
            await self.present_set_options(interaction, card, sets, original_message)

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
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json",
        }
        response = requests.get(card["prints_search_uri"], headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        return None

    async def present_set_options(self, interaction, card, sets, original_message):
        options = [nextcord.SelectOption(label=s["set_name"], value=s["id"]) for s in sets]
        select = nextcord.ui.Select(placeholder="Choose a set", options=options)

        async def select_callback(interaction):
            selected_set = next((s for s in sets if s["id"] == select.values[0]), None)
            if selected_set:
                await self.update_card_image(interaction, selected_set, original_message)

        select.callback = select_callback
        view = nextcord.ui.View()
        view.add_item(select)
        await original_message.edit(content="Select a set:", view=view, embed=None)

    async def update_card_image(self, interaction, selected_set, original_message):
        card = self.get_card_data_by_set(selected_set["id"])
        if not card:
            await interaction.followup.send("Could not retrieve details for the selected set.")
            return

        embed = self.create_card_embed(card)
        await original_message.edit(embed=embed, view=None, content=None)

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
    bot.add_cog(TCG(bot))
    boot_print("TCGCog has been added to the bot.")
