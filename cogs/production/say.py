import nextcord
from nextcord.ext import commands
from discord_webhook import DiscordWebhook
import asyncio

from server_configs.config import GUILD_ID
from server_configs.cogs_config import master_chief


character_avatars = {
    "Master Chief": "https://cdn.discordapp.com/attachments/1350599554818375811/1350738324247154742/master_chief_icon.png?ex=67d7d498&is=67d68318&hm=f795842687e7212baae6402a58dde8e16305f7f6907f934629e46b23bd1bf6b0&",
    "Cortana": "https://cdn.discordapp.com/attachments/1350599554818375811/1350744045428805672/cortana_icon.png?ex=67d7d9ec&is=67d6886c&hm=1c4b9fdb1a88d3e2f75d2eb01d6e7215c30f201fe99ea067fdc25dbebf9985c7&",
    "Madame Zeroni": "https://cdn.discordapp.com/attachments/758472892828090409/1351412712462221352/Madame_Zeroni.png?ex=67da48aa&is=67d8f72a&hm=a524ba5870a5e147cb3e6b5276cc351cc6380d7ca67f01cf2af291468f3be83c&",
    "Zuko": "https://cdn.discordapp.com/attachments/758472892828090409/1351412701665955880/Zuko.png?ex=67da48a8&is=67d8f728&hm=665e31242512db220c2ff64af371df588000ab2743a056d4d3dc8ef41bfef857&"
}

COST_TO_SAY = 200

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name='say', description="Send a message as a character. Costs 200 Shmeckles to use.", guild_ids=[GUILD_ID])
    async def say(self, 
                  interaction: nextcord.Interaction, 
                  character: str = nextcord.SlashOption(
                      name="character",
                      description="The character to speak as",
                      choices={"Master Chief": "Master Chief", "Cortana": "Cortana", "Madame Zeroni": "Madame Zeroni", "Zuko": "Zuko"}
                  ), 
                  message: str = nextcord.SlashOption(
                      name="message",
                      description="The message to say"
                  ),
                  channel: nextcord.abc.GuildChannel = nextcord.SlashOption(
                      name="channel",
                      description="Channel to send the message to (optional)",
                      required=False,
                      channel_types=[nextcord.ChannelType.text] 
                  )):
        
        await interaction.response.defer(ephemeral=True)

        economy_cog = self.bot.get_cog('Economy')
        if not economy_cog:
            await interaction.followup.send("Economy system is currently unavailable. Please try again later.", ephemeral=True)
            return

        user_id = interaction.user.id
        # Assuming economy_cog.get_user_balance is an async method
        current_balance = await economy_cog.get_user_balance(user_id) 

        if current_balance < COST_TO_SAY:
            await interaction.followup.send(f"You need {COST_TO_SAY} coins to use this command, but you only have {current_balance} coins.", ephemeral=True)
            return

        avatar_url = character_avatars.get(character)
        
        webhook_to_use_url = None
        temp_webhook_obj = None
        final_target_channel_obj = None # To store the channel object for mentioning

        try:
            if channel:
                # channel_types in SlashOption should ensure this, but an explicit check is safe.
                if not isinstance(channel, nextcord.TextChannel): 
                    await interaction.followup.send("The specified channel must be a text channel.", ephemeral=True)
                    return
                
                final_target_channel_obj = channel
                bot_member = interaction.guild.me
                if not final_target_channel_obj.permissions_for(bot_member).manage_webhooks:
                    await interaction.followup.send(f"I don't have permission to create webhooks in {final_target_channel_obj.mention}. Please grant 'Manage Webhooks' permission.", ephemeral=True)
                    return

                try:
                    temp_webhook_obj = await final_target_channel_obj.create_webhook(name=character, reason=f"Temporary webhook for /say command by {interaction.user}")
                    webhook_to_use_url = temp_webhook_obj.url
                except nextcord.Forbidden:
                    await interaction.followup.send(f"I'm forbidden from creating a webhook in {final_target_channel_obj.mention}. Please check my permissions.", ephemeral=True)
                    return
                except Exception as e:
                    print(f"Error creating webhook: {e}")
                    await interaction.followup.send("An error occurred while trying to create a webhook for the specified channel.", ephemeral=True)
                    return
            else:
                webhook_to_use_url = master_chief 
                # If you need to mention the default channel, you'll need its ID to fetch the channel object.
                # For example:
                # default_channel_id = YOUR_DEFAULT_WEBHOOK_CHANNEL_ID_HERE 
                # final_target_channel_obj = interaction.guild.get_channel(default_channel_id)

            if not webhook_to_use_url:
                await interaction.followup.send("Could not determine the webhook URL to use.", ephemeral=True)
                if temp_webhook_obj: # Clean up if created but URL somehow not set
                    await temp_webhook_obj.delete(reason="Cleanup after failed /say command (no URL)")
                return

            webhook = DiscordWebhook(url=webhook_to_use_url, content=message, username=character, avatar_url=avatar_url)
            
            loop = asyncio.get_event_loop()
            # discord-webhook's execute() is synchronous, run in executor
            response = await loop.run_in_executor(None, webhook.execute)

            if response.status_code in [200, 204]: # 200: OK, 204: No Content (still success for webhooks)
                # Assuming economy_cog.deduct_user_balance is an async method
                await economy_cog.deduct_user_balance(user_id, COST_TO_SAY) 
                
                channel_mention_str = f"in {final_target_channel_obj.mention}" if final_target_channel_obj else "to the pre-configured channel"
                await interaction.followup.send(f"Message sent as {character} {channel_mention_str}.", ephemeral=True)
                # For logging, get updated balance
                new_balance = await economy_cog.get_user_balance(user_id)
                print(f"Message sent as {character} by {interaction.user.name} ({user_id}) {channel_mention_str}: {message}. Cost: {COST_TO_SAY}. Balance remaining: {new_balance}")
            else:
                # Do not deduct if sending failed
                await interaction.followup.send(f"Failed to send message. Webhook response: {response.status_code} - {response.text}", ephemeral=True)
                print(f"Failed to send message as {character} by {interaction.user.name} ({user_id}): {response.status_code} - {response.text}")

        except Exception as e:
            print(f"An error occurred in /say command: {e}")
            await interaction.followup.send("An unexpected error occurred. Please try again later.", ephemeral=True)
        
        finally:
            if temp_webhook_obj:
                try:
                    await temp_webhook_obj.delete(reason="Cleanup after /say command")
                except Exception as e:
                    webhook_id_for_log = temp_webhook_obj.id if temp_webhook_obj else "Unknown ID"
                    print(f"Error deleting temporary webhook {webhook_id_for_log}: {e}")
        

def setup(bot):
    bot.add_cog(Say(bot))
    print("SayCog has been added to the bot.")