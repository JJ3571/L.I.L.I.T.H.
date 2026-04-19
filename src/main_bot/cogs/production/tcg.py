import nextcord
from nextcord.ext import commands
import re
import requests

from main_bot.boot_log import boot_print
from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.config import MANA_SYMBOLS
class TCG(commands.Cog, CogLogMixin):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="mtg", description="Magic: The Gathering commands")
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
            "Accept": "application/json"
        }
        response = requests.get(f"https://api.scryfall.com/cards/autocomplete?q={card_name}", headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get('data', [])
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
        if interaction.response.is_done():
            original_message = await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)
            original_message = await interaction.followup.send(embed=embed)

        sets = self.get_card_sets(card)
        if sets:
            await self.present_set_options(interaction, card, sets, original_message)


    def get_card_data(self, card_name):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json"
        }
        response = requests.get(f"https://api.scryfall.com/cards/named?exact={card_name}", headers=headers)
        if response.status_code == 200:
            return response.json()
        return None


    def get_card_sets(self, card):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json"
        }
        response = requests.get(card['prints_search_uri'], headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data.get('data', [])
        return None


    async def present_set_options(self, interaction, card, sets, original_message):
        options = [nextcord.SelectOption(label=set['set_name'], value=set['id']) for set in sets]
        select = nextcord.ui.Select(placeholder="Choose a set", options=options)

        async def select_callback(interaction):
            selected_set = next((set for set in sets if set['id'] == select.values[0]), None)
            if selected_set:
                await self.update_card_image(interaction, selected_set, original_message)

        select.callback = select_callback
        view = nextcord.ui.View()
        view.add_item(select)
        await original_message.edit(content="Select a set:", view=view, embed=None)


    async def update_card_image(self, interaction, selected_set, original_message):
        card = self.get_card_data_by_set(selected_set['id'])
        if not card:
            await interaction.followup.send(f"Could not retrieve details for the selected set.")
            return

        embed = self.create_card_embed(card)
        await original_message.edit(embed=embed, view=None, content=None)


    def create_card_embed(self, card):
        embed = nextcord.Embed(
            title=card['name'],
            description=self.format_mana(card.get('oracle_text', 'No description')),
            color=0x00ff00
        )
        image_url = card.get("image_uris", {}).get("border_crop")
        if image_url:
            embed.set_image(url=image_url)
        embed.add_field(name="Mana Cost", value=self.format_mana(card.get('mana_cost')), inline=True)
        embed.add_field(name="Type", value=card['type_line'], inline=True)
        if 'power' in card and 'toughness' in card:
            embed.add_field(name="Power/Toughness", value=f"{card['power']}/{card['toughness']}", inline=True)
        embed.set_footer(text=f"Set: {card['set_name']}")
        return embed


    def get_card_data_by_set(self, set_id):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json"
        }
        response = requests.get(f"https://api.scryfall.com/cards/{set_id}", headers=headers)
        if response.status_code == 200:
            return response.json()
        return None

    async def send_card_embed(self, interaction, card):
        embed = nextcord.Embed(
            title=card['name'],
            description=self.format_mana(card.get('oracle_text', 'No description')),
            color=0x00ff00
        )
        image_url = card.get("image_uris", {}).get("border_crop")
        if image_url:
            embed.set_image(url=image_url)
        embed.add_field(name="Mana Cost", value=self.format_mana(card.get('mana_cost')), inline=True)
        embed.add_field(name="Type", value=card['type_line'], inline=True)
        if 'power' in card and 'toughness' in card:
            embed.add_field(name="Power/Toughness", value=f"{card['power']}/{card['toughness']}", inline=True)
        embed.set_footer(text=f"Set: {card['set_name']}")
        
        await interaction.followup.send(embed=embed)

    def format_mana(self, text):
        if not text:
            return "None"

        def replace_symbol(match):
            symbol = match.group(1)
            if symbol in MANA_SYMBOLS:
                return MANA_SYMBOLS[symbol]
            return match.group(0)

        if text is None:
            self.cog_print("Warning: Mana cost text is None")
            return "None"

        return re.sub(r'\{(.*?)\}', replace_symbol, text)

def setup(bot):
    bot.add_cog(TCG(bot))
    boot_print("TCGCog has been added to the bot.")