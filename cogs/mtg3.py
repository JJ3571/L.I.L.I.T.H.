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
        card = self.get_card_data(card_name, fuzzy=True)
        if not card:
            await interaction.followup.send(f"No cards found with the name '{card_name}'.")
            return

        if 'object' in card and card['object'] == 'error':
            await interaction.followup.send(f"Multiple cards found with the name '{card_name}'. Please be more specific.")
            return

        await self.send_card_embed(interaction, card)

    def get_card_data(self, card_name, fuzzy=False):
        headers = {
            "User-Agent": "DiscordBot (JJ3571, v0.1)",
            "Accept": "application/json"
        }
        search_type = "fuzzy" if fuzzy else "exact"
        response = requests.get(f"https://api.scryfall.com/cards/named?{search_type}={card_name}", headers=headers)
        if response.status_code == 200:
            return response.json()
        return None

    async def send_card_embed(self, interaction, card):
        embed = nextcord.Embed(title=card['name'], description=card.get('oracle_text', 'No description'), color=0x1F8B4C)
        image_url = card.get("image_uris", {}).get("normal")
        if image_url:
            embed.set_image(url=image_url)
        embed.add_field(name="Set", value=card['set_name'], inline=True)
        embed.add_field(name="Type", value=card['type_line'], inline=True)
        embed.add_field(name="Mana Cost", value=self.format_mana_cost(card.get('mana_cost')), inline=True)
        if 'power' in card and 'toughness' in card:
            embed.add_field(name="Power/Toughness", value=f"{card['power']}/{card['toughness']}", inline=True)

        await interaction.followup.send(embed=embed)

    def format_mana_cost(self, mana_cost):
        if not mana_cost:
            return "None"
        mana_symbols = {
            "W": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/W.svg",
            "U": "https://cdn.discordapp.com/attachments/807342895656730685/1348498842466783293/U.png?ex=67cfaee9&is=67ce5d69&hm=552b14eebecb4d61f781195a0200c137b6c21e5938ae04264ef190807e6b447f&",
            "B": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/B.svg",
            "R": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/R.svg",
            "G": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/G.svg",
            "C": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/C.svg",
            "X": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/X.svg",
            "Y": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/Y.svg",
            "Z": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/Z.svg",
            "S": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/S.svg",
            "0": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/0.svg",
            "1": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/1.svg",
            "2": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/2.svg",
            "3": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/3.svg",
            "4": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/4.svg",
            "5": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/5.svg",
            "6": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/6.svg",
            "7": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/7.svg",
            "8": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/8.svg",
            "9": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/9.svg",
            "10": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/10.svg",
            "11": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/11.svg",
            "12": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/12.svg",
            "13": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/13.svg",
            "14": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/14.svg",
            "15": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/15.svg",
            "16": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/16.svg",
            "17": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/17.svg",
            "18": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/18.svg",
            "19": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/19.svg",
            "20": "https://c2.scryfall.com/file/scryfall-symbols/card-symbols/20.svg",
        }
        formatted_cost = ""
        for symbol in re.findall(r'\{(.*?)\}', mana_cost):
            if symbol in mana_symbols:
                formatted_cost += f"[{symbol}]({mana_symbols[symbol]}) "
            else:
                formatted_cost += f"{symbol} "
        return formatted_cost.strip()

def setup(bot):
    bot.add_cog(TCG(bot))