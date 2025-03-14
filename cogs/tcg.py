import nextcord
from nextcord.ext import commands
import re
import requests

class TCG(commands.Cog):
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
            original_message = await interaction.original_response()
            await original_message.edit(embed=embed, view=None)
        else:
            await interaction.response.send_message(embed=embed) # Removed view=None

            original_message = await interaction.original_response()

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
        embed.add_field(name="Set", value=card['set_name'], inline=True)
        embed.add_field(name="Type", value=card['type_line'], inline=True)
        embed.add_field(name="Mana Cost", value=self.format_mana(card.get('mana_cost')), inline=True)
        if 'power' in card and 'toughness' in card:
            embed.add_field(name="Power/Toughness", value=f"{card['power']}/{card['toughness']}", inline=True)
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
        embed.add_field(name="Set", value=card['set_name'], inline=True)
        embed.add_field(name="Type", value=card['type_line'], inline=True)
        embed.add_field(name="Mana Cost", value=self.format_mana(card.get('mana_cost')), inline=True)
        if 'power' in card and 'toughness' in card:
            embed.add_field(name="Power/Toughness", value=f"{card['power']}/{card['toughness']}", inline=True)

        await interaction.followup.send(embed=embed)

    def format_mana(self, text):
        if not text:
            return "None"
        mana_symbols = {
            "W": 1349143103499669534,  # Replace with the actual emoji ID for W
            "U": 1348522558865145938,  # Replace with the actual emoji ID for U
            "B": 1349141485421072534,  # Replace with the actual emoji ID for B
            "R": 1349142442179559467,  # Replace with the actual emoji ID for R
            "G": 1349142116856496289,  # Replace with the actual emoji ID for G
            "C": 1349140792358338731,  # Replace with the actual emoji ID for C
            "X": 1349144292677128314,  # Replace with the actual emoji ID for X
            "Y": 1349144384272207974,  # Replace with the actual emoji ID for Y
            "Z": 1349144404870303785,  # Replace with the actual emoji ID for Z
            "S": 1349142680109580368,  # Replace with the actual emoji ID for S
            "0": 1349140870581981244,  # Replace with the actual emoji ID for 0
            "1": 1349140885790654594,  # Replace with the actual emoji ID for 1
            "2": 1349140901406052372,  # Replace with the actual emoji ID for 2
            "3": 1349141008767516785,  # Replace with the actual emoji ID for 3
            "4": 1349141024055889920,  # Replace with the actual emoji ID for 4
            "5": 1349141037469270026,  # Replace with the actual emoji ID for 5
            "6": 1349141052690530455,  # Replace with the actual emoji ID for 6
            "7": 1349141067093512274,  # Replace with the actual emoji ID for 7
            "8": 1349141082734071909,  # Replace with the actual emoji ID for 8
            "9": 1349141096059502653,  # Replace with the actual emoji ID for 9
            "10": 12365,  # Replace with the actual emoji ID for 10
            "11": 12366,  # Replace with the actual emoji ID for 11
            "12": 12367,  # Replace with the actual emoji ID for 12
            "13": 12368,  # Replace with the actual emoji ID for 13
            "14": 12369,  # Replace with the actual emoji ID for 14
            "15": 12370,  # Replace with the actual emoji ID for 15
            "16": 12371,  # Replace with the actual emoji ID for 16
            "17": 12372,  # Replace with the actual emoji ID for 17
            "18": 12373,  # Replace with the actual emoji ID for 18
            "19": 12374,  # Replace with the actual emoji ID for 19
            "20": 12375,  # Replace with the actual emoji ID for 20
            "q": 1349142403814133894,
            "t": 1349142699688857684,
        }
        def replace_symbol(match):
            symbol = match.group(1)
            if symbol in mana_symbols:
                emoji = self.bot.get_emoji(mana_symbols[symbol])
                return str(emoji)
            return match.group(0)

        return re.sub(r'\{(.*?)\}', replace_symbol, text)

def setup(bot):
    bot.add_cog(TCG(bot))
    print("TCGCog has been added to the bot.")