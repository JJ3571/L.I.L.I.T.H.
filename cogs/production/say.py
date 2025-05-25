import nextcord
from nextcord.ext import commands
from discord_webhook import DiscordWebhook
import asyncio
import os
from google import genai
from google.genai import types

from server_configs.config import GUILD_ID, GEMINI_API_KEY
from server_configs.cogs_config import webhook_url, character_avatars, ZERONI_REACTION_EMOJI, COMMUNITY_NOTES_REACTION_EMOJI


COST_TO_SAY = 200
COMMUNITY_NOTES_REACTION_EMOJI


def generate_zeroni(input_text: str):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
    )

    model = "gemini-2.5-flash-preview-05-20"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=input_text),
            ],
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
        system_instruction=[
            types.Part.from_text(text="""You are Madame Zeroni from the story Holes. You are an old, wise, one-legged woman, possibly of Egyptian or Romani descent. You are known for giving advice, making bargains, and understanding the weight of promises. You gave Elya Yelnats a piglet and a song in exchange for a promise he broke, leading to a curse on his family. Speak with worldly wisdom, a touch of cynicism, and directness. Do not suffer fools gladly. Your concerns revolve around fate, promises, and consequences."""),
        ],
    )

    response_text_parts = []
    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            response_text_parts.append(chunk.text)
        return "".join(response_text_parts)
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return None
    
def generate_notes(input_text: str):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
    )

    model = "gemini-2.5-flash-preview-05-20"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=input_text),
            ],
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
        system_instruction=[
            types.Part.from_text(text="""
                                Generate a helpful and neutral Community Note for the following content. The note should:
                                1. Evaluate the accuracy of the claim. Keep it neutral and cite high-quality sources to support the information provided. Do not include direct links as they may change over time. 
                                2. Provide factual clarification or necessary context.
                                3. Be concise and easy to understand.
                                4. If the content is a question, provide a thoughtful and informative answer. Elaborate on specifics where beneficial.
                                5. Maintain a neutral, non-argumentative tone.
            """),
        ],
    )

    response_text_parts = []
    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            response_text_parts.append(chunk.text)
        return "".join(response_text_parts)
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return None

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name='say', description="Send a message as a character. Costs 200 Shmeckles to use.", guild_ids=[GUILD_ID])
    async def say(self, 
                  interaction: nextcord.Interaction, 
                  character: str = nextcord.SlashOption(
                      name="character",
                      description="The character to speak as",
                      choices={"Master Chief": "Master Chief", "Cortana": "Cortana", "Madame Zeroni": "Madame Zeroni", "Zuko": "Zuko", "Babu Frik": "Babu Frik", "Dr. Pepper": "Dr. Pepper"}    
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
                webhook_to_use_url = webhook_url
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


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: nextcord.RawReactionActionEvent):
        # Ignore reactions from bots
        if payload.user_id == self.bot.user.id:
            return
        
        # Fetch the user who reacted
        user = self.bot.get_user(payload.user_id)
        if user is None: # Fallback if user not in cache
            try:
                user = await self.bot.fetch_user(payload.user_id)
            except nextcord.NotFound:
                print(f"[REACTION DEBUG] User {payload.user_id} not found.")
                return
        
        if user.bot: # Check again after fetching, just in case
            return

        # Fetch the channel and message
        try:
            channel = self.bot.get_channel(payload.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(payload.channel_id)
            
            if not isinstance(channel, nextcord.TextChannel): # Ensure it's a text channel
                return

            message = await channel.fetch_message(payload.message_id)
        except nextcord.NotFound:
            print(f"[REACTION DEBUG] Message or Channel not found for reaction (Msg ID: {payload.message_id}, Chan ID: {payload.channel_id}).")
            return
        except nextcord.Forbidden:
            print(f"[REACTION DEBUG] Bot lacks permissions to fetch message/channel for reaction (Msg ID: {payload.message_id}, Chan ID: {payload.channel_id}).")
            return
        except Exception as e:
            print(f"[REACTION DEBUG] Error fetching message/channel: {e}")
            return

        generator_function = None
        character_name = None
        response_prefix = None

        if str(payload.emoji) == ZERONI_REACTION_EMOJI and message.content:
            print(f"'{ZERONI_REACTION_EMOJI}' reaction detected from {user.name} on message in #{channel.name}")
            generator_function = generate_zeroni
            character_name = "Madame Zeroni"
            response_prefix = "Madame Zeroni (via raw reaction)"

        elif str(payload.emoji) == COMMUNITY_NOTES_REACTION_EMOJI and message.content:
            print(f"'{COMMUNITY_NOTES_REACTION_EMOJI}' reaction detected from {user.name} on message in #{channel.name}")
            generator_function = generate_notes
            character_name = "Community Note"
            response_prefix = "Community Note (via raw reaction)"
        else:
            return

        try:
            loop = asyncio.get_event_loop()
            api_response_content = await loop.run_in_executor(None, generator_function, message.content)

            if not api_response_content:
                print(f"{response_prefix} had no response for: \"{message.content[:50]}...\"")
                return

            embed_description = f"{api_response_content}\n\n[Jump to original message]({message.jump_url})"

            embed = nextcord.Embed(
                description=embed_description,
                color=nextcord.Color.blue() # You can choose a color
            )

            if character_name == "Community Note":
                # Set the bot as the author for Community Notes
                bot_user = self.bot.user
                embed.set_author(name=f"{bot_user.display_name} [Community Note]", icon_url=bot_user.display_avatar.url if bot_user.display_avatar else nextcord.Embed.Empty)
            elif character_name:
                # For other characters, use the character_avatars
                avatar_url = character_avatars.get(character_name)
                author_icon_url = avatar_url if avatar_url and isinstance(avatar_url, str) and avatar_url.startswith(('http://', 'https://')) else nextcord.Embed.Empty
                embed.set_author(name=character_name, icon_url=author_icon_url)
            
            # Add a footer to indicate it was triggered by a reaction
            user_display_avatar_url = user.display_avatar.url if user.display_avatar else nextcord.Embed.Empty
            embed.set_footer(text=f"Triggered by {user.display_name}'s reaction", icon_url=user_display_avatar_url)
            embed.timestamp = nextcord.utils.utcnow()

            # Send the embed to the channel where the reaction occurred
            await channel.send(embed=embed)
            print(f"Sent {character_name} embed response to #{channel.name} for message ID {message.id}")

        except nextcord.Forbidden:
            print(f"Bot lacks 'Send Messages' or 'Embed Links' permission in {channel.name} for {character_name} reaction response.")
            # You might want to notify the user or log this more formally
            # await message.reply(f"I can't post {character_name}'s response here. I might be missing 'Send Messages' or 'Embed Links' permissions in {channel.mention}.", delete_after=30)
        except Exception as e:
            print(f"An error occurred in on_raw_reaction_add for {character_name}: {e}")


def setup(bot):
    bot.add_cog(Say(bot))
    print("SayCog has been added to the bot.")