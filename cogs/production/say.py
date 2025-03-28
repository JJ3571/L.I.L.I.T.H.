import nextcord
from nextcord.ext import commands
from discord_webhook import DiscordWebhook

from server_configs.cogs_config import master_chief

character_avatars = {
    "Master Chief": "https://cdn.discordapp.com/attachments/1350599554818375811/1350738324247154742/master_chief_icon.png?ex=67d7d498&is=67d68318&hm=f795842687e7212baae6402a58dde8e16305f7f6907f934629e46b23bd1bf6b0&",
    "Cortana": "https://cdn.discordapp.com/attachments/1350599554818375811/1350744045428805672/cortana_icon.png?ex=67d7d9ec&is=67d6886c&hm=1c4b9fdb1a88d3e2f75d2eb01d6e7215c30f201fe99ea067fdc25dbebf9985c7&",
    "Madame Zeroni": "https://cdn.discordapp.com/attachments/758472892828090409/1351412712462221352/Madame_Zeroni.png?ex=67da48aa&is=67d8f72a&hm=a524ba5870a5e147cb3e6b5276cc351cc6380d7ca67f01cf2af291468f3be83c&",
    "Zuko": "https://cdn.discordapp.com/attachments/758472892828090409/1351412701665955880/Zuko.png?ex=67da48a8&is=67d8f728&hm=665e31242512db220c2ff64af371df588000ab2743a056d4d3dc8ef41bfef857&"
}

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name='say', description="Send a message as a character")
    async def say(self, interaction: nextcord.Interaction, character: str = nextcord.SlashOption(choices={"Master Chief": "Master Chief", "Cortana": "Cortana","Madame Zeroni":"Madame Zeroni", "Zuko":"Zuko"}), *, message: str):
        webhook_url = master_chief
        avatar_url = character_avatars.get(character, None)  # Get the avatar URL for the character
        webhook = DiscordWebhook(url=webhook_url, content=message, username=character, avatar_url=avatar_url)
        response = webhook.execute()
        if response.status_code == 200:
            print(f"Message sent as {character}: {message}") 
        else:
            print(f"Failed to send message: {response.status_code} - {response.text}")
        await interaction.response.send_message(f"Message sent as {character}: {message}", ephemeral=True)
        

def setup(bot):
    bot.add_cog(Say(bot))
    print("SayCog has been added to the bot.")