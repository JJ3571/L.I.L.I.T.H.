import nextcord
from nextcord.ext import commands
from discord_webhook import DiscordWebhook
import asyncio
import os
import re
import time
import colorsys
import io
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

from server_configs.config import GUILD_ID, GEMINI_API_KEY
from server_configs.cogs_config import webhook_url, character_avatars, ZERONI_REACTION_EMOJI, COMMUNITY_NOTES_REACTION_EMOJI


COST_TO_SAY = 200
COMMUNITY_NOTES_REACTION_EMOJI

class ComplementaryColorView(nextcord.ui.View):
    def __init__(self, original_hex: str, comp_hex: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.original_hex = original_hex
        self.comp_hex = comp_hex
    
    @nextcord.ui.button(label=f"View Complementary Color", style=nextcord.ButtonStyle.secondary, emoji="🔄")
    async def show_complementary(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Update button label to show the complementary color
        button.label = f"View {self.comp_hex}"
        
        # Convert complementary color to various formats
        comp_r, comp_g, comp_b = hex_to_rgb(self.comp_hex)
        comp_hsv_h, comp_hsv_s, comp_hsv_v = rgb_to_hsv(comp_r, comp_g, comp_b)
        comp_hsl_h, comp_hsl_s, comp_hsl_l = rgb_to_hsl(comp_r, comp_g, comp_b)
        comp_c, comp_m, comp_y, comp_k = rgb_to_cmyk(comp_r, comp_g, comp_b)
        
        # Get complementary of complementary (which is the original color)
        back_to_original_r, back_to_original_g, back_to_original_b = get_complementary_color(comp_r, comp_g, comp_b)
        back_to_original_hex = rgb_to_hex(back_to_original_r, back_to_original_g, back_to_original_b)
        
        # Create color swatch for complementary color
        comp_color_swatch = create_color_swatch(self.comp_hex)
        
        # Create embed for complementary color
        embed = nextcord.Embed(
            title=f"Complementary Color: {self.comp_hex}",
            color=int(self.comp_hex.lstrip('#'), 16),
            description=f"Complementary color of **{self.original_hex}**"
        )
        
        # Add color format fields
        embed.add_field(
            name="Color Formats",
            value=f"**HEX:** {self.comp_hex}\n"
                  f"**RGB:** {comp_r}, {comp_g}, {comp_b}\n"
                  f"**HSV:** {comp_hsv_h}°, {comp_hsv_s}%, {comp_hsv_v}%\n"
                  f"**HSL:** {comp_hsl_h}°, {comp_hsl_s}%, {comp_hsl_l}%\n"
                  f"**CMYK:** {comp_c}%, {comp_m}%, {comp_y}%, {comp_k}%",
            inline=True
        )
        
        # Show relationship to original color
        embed.add_field(
            name="Original Color",
            value=f"**HEX:** {self.original_hex}\n"
                  f"**RGB:** {back_to_original_r}, {back_to_original_g}, {back_to_original_b}",
            inline=True
        )
        
        # Add color properties
        comp_brightness = get_color_brightness(comp_r, comp_g, comp_b)
        comp_brightness_desc = "Light" if comp_brightness > 0.5 else "Dark"
        
        embed.add_field(
            name="Properties",
            value=f"**Brightness:** {comp_brightness:.2f} ({comp_brightness_desc})\n"
                  f"**Best Text Color:** {'Black' if comp_brightness > 0.5 else 'White'}",
            inline=True
        )
        
        # Set footer
        embed.set_footer(
            text=f"Complementary of {self.original_hex} • Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else nextcord.Embed.Empty
        )
        embed.timestamp = nextcord.utils.utcnow()
        
        # Upload complementary color swatch and respond
        file = nextcord.File(comp_color_swatch, filename=f"comp_color_{self.comp_hex.lstrip('#')}.png")
        embed.set_image(url=f"attachment://comp_color_{self.comp_hex.lstrip('#')}.png")
        
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
        print(f"Sent complementary color {self.comp_hex} for original {self.original_hex}")
    
    async def on_timeout(self):
        # Disable the button when the view times out
        for item in self.children:
            item.disabled = True


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
    
def generate_notes(input_text: str, include_web_search: bool = True):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
    )

    model = "gemini-2.5-flash-preview-05-20"
    
    system_instruction = """
    Generate a helpful and neutral Community Note for the following content. The note should:
    1. Evaluate the accuracy of the claim using current, reliable information. If web search is available, prioritize recent and authoritative sources.
    2. Provide factual clarification or necessary context with specific details when possible.
    3. Be concise yet comprehensive - aim for clarity and completeness.
    4. If the content is a question, provide a thorough and informative answer with relevant examples or specifics.
    5. Maintain a neutral, non-argumentative tone while being helpful and informative.
    6. When citing information, mention the general source type (e.g., "according to recent studies", "official sources indicate", "current data shows") without direct links.
    7. If information appears outdated or requires current context, note this and provide updated information when available.
    """
    
    content_parts = [types.Part.from_text(text=input_text)]
    
    if include_web_search:
        # Add web search instruction to get current information
        web_search_prompt = f"""
        Please search for current, accurate information related to this content to provide the most up-to-date and reliable response: {input_text}
        """
        content_parts.append(types.Part.from_text(text=web_search_prompt))

    contents = [
        types.Content(
            role="user",
            parts=content_parts,
        ),
    ]
    
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
        system_instruction=[types.Part.from_text(text=system_instruction)],
        tools=[types.Tool(google_search=types.GoogleSearch())] if include_web_search else None,
    )

    response_text_parts = []
    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                response_text_parts.append(chunk.text)
        return "".join(response_text_parts)
    except Exception as e:
        print(f"Error during Gemini API call with web search: {e}")
        # Fallback to basic version without web search
        if include_web_search:
            print("Retrying without web search...")
            return generate_notes(input_text, include_web_search=False)
        return None

def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB to hex color"""
    return f"#{r:02x}{g:02x}{b:02x}".upper()

def rgb_to_hsv(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Convert RGB to HSV"""
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    return (int(h*360), int(s*100), int(v*100))

def rgb_to_hsl(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Convert RGB to HSL"""
    h, l, s = colorsys.rgb_to_hls(r/255.0, g/255.0, b/255.0)
    return (int(h*360), int(s*100), int(l*100))

def rgb_to_cmyk(r: int, g: int, b: int) -> tuple[int, int, int, int]:
    """Convert RGB to CMYK"""
    # Normalize RGB values to 0-1 range
    r, g, b = r/255.0, g/255.0, b/255.0
    
    # Calculate K (black)
    k = 1 - max(r, g, b)
    
    # Avoid division by zero
    if k == 1:
        return (0, 0, 0, 100)
    
    # Calculate CMY
    c = (1 - r - k) / (1 - k)
    m = (1 - g - k) / (1 - k)
    y = (1 - b - k) / (1 - k)
    
    return (int(c*100), int(m*100), int(y*100), int(k*100))

def get_complementary_color(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Get complementary color (opposite on color wheel)"""
    return (255 - r, 255 - g, 255 - b)

def get_color_brightness(r: int, g: int, b: int) -> float:
    """Calculate perceived brightness of color (0-1 scale)"""
    # Using relative luminance formula
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255

def create_color_swatch(hex_color: str, size: tuple[int, int] = (400, 200)) -> io.BytesIO:
    """Create a color swatch image"""
    r, g, b = hex_to_rgb(hex_color)
    
    # Create image with the color
    img = Image.new('RGB', size, (r, g, b))
    draw = ImageDraw.Draw(img)
    
    # Add a subtle border
    border_color = (255, 255, 255) if get_color_brightness(r, g, b) < 0.5 else (0, 0, 0)
    draw.rectangle([(0, 0), (size[0]-1, size[1]-1)], outline=border_color, width=3)
    
    # Save to BytesIO
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    return img_buffer

def interpolate_color(color1: tuple[int, int, int], color2: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Interpolate between two RGB colors"""
    r1, g1, b1 = color1
    r2, g2, b2 = color2
    
    r = int(r1 + (r2 - r1) * factor)
    g = int(g1 + (g2 - g1) * factor)
    b = int(b1 + (b2 - b1) * factor)
    
    return (r, g, b)

def create_gradient_swatch(hex_color1: str, hex_color2: str, size: tuple[int, int] = (400, 200), direction: str = "horizontal") -> io.BytesIO:
    """Create a gradient between two colors"""
    r1, g1, b1 = hex_to_rgb(hex_color1)
    r2, g2, b2 = hex_to_rgb(hex_color2)
    
    img = Image.new('RGB', size)
    draw = ImageDraw.Draw(img)
    
    if direction == "horizontal":
        # Horizontal gradient (left to right)
        for x in range(size[0]):
            factor = x / (size[0] - 1)
            color = interpolate_color((r1, g1, b1), (r2, g2, b2), factor)
            draw.line([(x, 0), (x, size[1])], fill=color)
    elif direction == "vertical":
        # Vertical gradient (top to bottom)
        for y in range(size[1]):
            factor = y / (size[1] - 1)
            color = interpolate_color((r1, g1, b1), (r2, g2, b2), factor)
            draw.line([(0, y), (size[0], y)], fill=color)
    elif direction == "diagonal":
        # Diagonal gradient
        for x in range(size[0]):
            for y in range(size[1]):
                factor = (x + y) / (size[0] + size[1] - 2)
                color = interpolate_color((r1, g1, b1), (r2, g2, b2), factor)
                draw.point((x, y), fill=color)
    
    # Add border with averaged color brightness
    avg_brightness = (get_color_brightness(r1, g1, b1) + get_color_brightness(r2, g2, b2)) / 2
    border_color = (255, 255, 255) if avg_brightness < 0.5 else (0, 0, 0)
    draw.rectangle([(0, 0), (size[0]-1, size[1]-1)], outline=border_color, width=3)
    
    # Save to BytesIO
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    return img_buffer

def get_gradient_midpoint_color(hex_color1: str, hex_color2: str) -> str:
    """Get the midpoint color of a gradient"""
    r1, g1, b1 = hex_to_rgb(hex_color1)
    r2, g2, b2 = hex_to_rgb(hex_color2)
    mid_color = interpolate_color((r1, g1, b1), (r2, g2, b2), 0.5)
    return rgb_to_hex(*mid_color)

class Say(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Rate limiting to prevent spam
        self.user_cooldowns = {}
        self.cooldown_duration = 15  # seconds between AI responses per user

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
            generator_function = lambda text: generate_notes(text, True)  # Enable web search for reactions too
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

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        """Handle bot mentions, replies to bot messages, and hex color detection"""
        # Ignore messages from bots (including self)
        if message.author.bot:
            return
        
        # Ignore messages without content
        if not message.content.strip():
            return
        
        # Check for hex colors first (since they don't require rate limiting)
        hex_pattern = r'#[0-9A-Fa-f]{6}\b'
        hex_matches = re.findall(hex_pattern, message.content)
        
        if hex_matches:
            # Handle hex color detection (supports 1-2 colors)
            colors_to_process = hex_matches[:2]  # Limit to first 2 colors
            await self._handle_hex_colors(message, colors_to_process)
            return  # Don't process as mention/reply if it's a hex color
        
        # Check if bot is mentioned
        bot_mentioned = self.bot.user in message.mentions
        
        # Check if this is a reply to any message and get the referenced message
        referenced_message = None
        is_reply_to_bot = False
        is_reply_with_mention = False
        
        if message.reference and message.reference.message_id:
            try:
                referenced_message = await message.channel.fetch_message(message.reference.message_id)
                is_reply_to_bot = referenced_message.author == self.bot.user
                is_reply_with_mention = bot_mentioned and referenced_message.author != self.bot.user
            except (nextcord.NotFound, nextcord.Forbidden):
                referenced_message = None
                is_reply_to_bot = False
                is_reply_with_mention = False
        
        # Process if bot was mentioned, replying to bot, or mentioned in a reply to someone else
        if bot_mentioned or is_reply_to_bot:
            # Check rate limiting
            current_time = time.time()
            user_id = message.author.id
            
            if user_id in self.user_cooldowns:
                time_since_last = current_time - self.user_cooldowns[user_id]
                if time_since_last < self.cooldown_duration:
                    # User is on cooldown, send ephemeral message
                    remaining_time = int(self.cooldown_duration - time_since_last)
                    try:
                        await message.reply(
                            f"⏰ Please wait {remaining_time} more seconds before requesting another AI response.",
                            delete_after=10,
                            mention_author=False
                        )
                    except nextcord.Forbidden:
                        # If we can't send a message, try to react with a clock emoji
                        try:
                            await message.add_reaction("⏰")
                        except:
                            pass  # Silent fail if we can't even react
                    return
            
            # Update cooldown
            self.user_cooldowns[user_id] = current_time
            
            # Determine trigger type for logging and context
            if is_reply_with_mention:
                trigger_type = "mention in reply"
            elif bot_mentioned:
                trigger_type = "mention"
            else:
                trigger_type = "reply"
            
            print(f"Bot {trigger_type} detected from {message.author.name} in #{message.channel.name}: {message.content[:100]}...")
            
            # Process the message content with context
            content_to_process = message.content
            
            # Remove bot mention from content if present
            if bot_mentioned:
                content_to_process = re.sub(f'<@!?{self.bot.user.id}>', '', content_to_process).strip()
            
            # Build context-aware prompt
            if is_reply_with_mention and referenced_message:
                # When bot is mentioned in a reply, include both the original message and the reply
                context_prompt = f"""Original message from {referenced_message.author.display_name}: "{referenced_message.content}"

Reply from {message.author.display_name} (mentioning you): "{content_to_process}"

Please respond considering both the original message context and the user's reply."""
            elif is_reply_to_bot and referenced_message:
                # When replying to bot, include the bot's previous message for context
                context_prompt = f"""Previous bot message: "{referenced_message.content}"

User's reply: "{content_to_process}"

Please respond to the user's reply in context of the previous conversation."""
            else:
                # Direct mention without reply context
                context_prompt = content_to_process
            
            # Skip if no meaningful content remains
            if not content_to_process and not (is_reply_with_mention and referenced_message):
                return
            
            try:
                # Generate response using enhanced Gemini with web search
                loop = asyncio.get_event_loop()
                api_response_content = await loop.run_in_executor(
                    None, 
                    generate_notes, 
                    context_prompt,
                    True  # Enable web search
                )

                if not api_response_content:
                    print(f"No response generated for {trigger_type}: \"{content_to_process[:50]}...\"")
                    return

                # Create embed response
                embed_description = f"{api_response_content}"
                
                # Add context links based on trigger type
                if is_reply_with_mention and referenced_message:
                    embed_description += f"\n\n[Responding to this conversation]({message.reference.jump_url})"
                elif is_reply_to_bot and referenced_message:
                    embed_description += f"\n\n[In reply to this message]({message.reference.jump_url})"

                embed = nextcord.Embed(
                    description=embed_description,
                    color=nextcord.Color.blue()
                )

                # Set the bot as the author for these responses
                bot_user = self.bot.user
                embed.set_author(
                    name=bot_user.display_name, 
                    icon_url=bot_user.display_avatar.url if bot_user.display_avatar else nextcord.Embed.Empty
                )
                
                # Add footer to indicate trigger method
                user_display_avatar_url = message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
                if is_reply_with_mention:
                    footer_text = f"Triggered by {message.author.display_name}'s mention in reply"
                elif bot_mentioned:
                    footer_text = f"Triggered by {message.author.display_name}'s mention"
                else:
                    footer_text = f"Triggered by {message.author.display_name}'s reply"
                
                embed.set_footer(
                    text=footer_text, 
                    icon_url=user_display_avatar_url
                )
                embed.timestamp = nextcord.utils.utcnow()

                # Send the response
                await message.reply(embed=embed, mention_author=False)
                print(f"Sent enhanced response to {trigger_type} in #{message.channel.name}")

            except nextcord.Forbidden:
                print(f"Bot lacks permissions to respond to {trigger_type} in {message.channel.name}")
                try:
                    # Try to react with an emoji to indicate we saw the message but can't respond
                    await message.add_reaction("👀")
                except:
                    pass  # If we can't even react, just silently fail
            except Exception as e:
                print(f"An error occurred processing {trigger_type}: {e}")

    async def _handle_hex_colors(self, message: nextcord.Message, hex_colors: list[str]):
        """Handle hex color detection and display color information"""
        try:
            # Handle single color vs gradient
            if len(hex_colors) == 1:
                await self._handle_single_color(message, hex_colors[0])
            elif len(hex_colors) >= 2:
                await self._handle_gradient_colors(message, hex_colors[0], hex_colors[1])
            
        except nextcord.Forbidden:
            print(f"Bot lacks permissions to respond with color info in {message.channel.name}")
            try:
                await message.add_reaction("🎨")
            except:
                pass
        except Exception as e:
            print(f"An error occurred processing hex colors {hex_colors}: {e}")

    async def _handle_single_color(self, message: nextcord.Message, hex_color: str):
        """Handle single hex color display"""
        hex_color = hex_color.upper()
        print(f"Hex color {hex_color} detected from {message.author.name} in #{message.channel.name}")
        
        # Convert to various color formats
        r, g, b = hex_to_rgb(hex_color)
        hsv_h, hsv_s, hsv_v = rgb_to_hsv(r, g, b)
        hsl_h, hsl_s, hsl_l = rgb_to_hsl(r, g, b)
        c, m, y, k = rgb_to_cmyk(r, g, b)
        comp_r, comp_g, comp_b = get_complementary_color(r, g, b)
        comp_hex = rgb_to_hex(comp_r, comp_g, comp_b)
        
        # Create color swatch image
        color_swatch = create_color_swatch(hex_color)
        
        # Create embed with color information
        embed = nextcord.Embed(
            title=f"Color Information: {hex_color}",
            color=int(hex_color.lstrip('#'), 16),
            description=f"Here's detailed information about the color **{hex_color}**"
        )
        
        # Add color format fields
        embed.add_field(
            name="Color Formats",
            value=f"**HEX:** {hex_color}\n"
                  f"**RGB:** {r}, {g}, {b}\n"
                  f"**HSV:** {hsv_h}°, {hsv_s}%, {hsv_v}%\n"
                  f"**HSL:** {hsl_h}°, {hsl_s}%, {hsl_l}%\n"
                  f"**CMYK:** {c}%, {m}%, {y}%, {k}%",
            inline=True
        )
        
        # Add complementary color info
        embed.add_field(
            name="Complementary Color",
            value=f"**HEX:** {comp_hex}\n"
                  f"**RGB:** {comp_r}, {comp_g}, {comp_b}",
            inline=True
        )
        
        # Add color properties
        brightness = get_color_brightness(r, g, b)
        brightness_desc = "Light" if brightness > 0.5 else "Dark"
        
        embed.add_field(
            name="Properties",
            value=f"**Brightness:** {brightness:.2f} ({brightness_desc})\n"
                  f"**Best Text Color:** {'Black' if brightness > 0.5 else 'White'}",
            inline=True
        )
        
        # Set footer
        embed.set_footer(
            text=f"Color detected from {message.author.display_name}'s message",
            icon_url=message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
        )
        embed.timestamp = nextcord.utils.utcnow()
        
        # Create view with complementary color button
        view = ComplementaryColorView(hex_color, comp_hex)
        view.children[0].label = f"View {comp_hex}"
        
        # Upload color swatch as file and send embed
        file = nextcord.File(color_swatch, filename=f"color_{hex_color.lstrip('#')}.png")
        embed.set_image(url=f"attachment://color_{hex_color.lstrip('#')}.png")
        
        await message.reply(embed=embed, file=file, view=view, mention_author=False)
        print(f"Sent color information for {hex_color} in #{message.channel.name}")

    async def _handle_gradient_colors(self, message: nextcord.Message, hex_color1: str, hex_color2: str):
        """Handle gradient between two hex colors"""
        hex_color1 = hex_color1.upper()
        hex_color2 = hex_color2.upper()
        print(f"Gradient {hex_color1} → {hex_color2} detected from {message.author.name} in #{message.channel.name}")
        
        # Get color information for both colors
        r1, g1, b1 = hex_to_rgb(hex_color1)
        r2, g2, b2 = hex_to_rgb(hex_color2)
        
        # Get midpoint color for embed color
        midpoint_hex = get_gradient_midpoint_color(hex_color1, hex_color2)
        
        # Create gradient image
        gradient_swatch = create_gradient_swatch(hex_color1, hex_color2, size=(500, 200))
        
        # Create embed with gradient information
        embed = nextcord.Embed(
            title=f"Color Gradient: {hex_color1} → {hex_color2}",
            color=int(midpoint_hex.lstrip('#'), 16),
            description=f"Beautiful gradient between **{hex_color1}** and **{hex_color2}**"
        )
        
        # Start color info
        hsv1_h, hsv1_s, hsv1_v = rgb_to_hsv(r1, g1, b1)
        
        embed.add_field(
            name=f"Start Color ({hex_color1})",
            value=f"**RGB:** {r1}, {g1}, {b1}\n"
                  f"**HSV:** {hsv1_h}°, {hsv1_s}%, {hsv1_v}%",
            inline=True
        )
        
        # End color info
        hsv2_h, hsv2_s, hsv2_v = rgb_to_hsv(r2, g2, b2)
        
        embed.add_field(
            name=f"End Color ({hex_color2})",
            value=f"**RGB:** {r2}, {g2}, {b2}\n"
                  f"**HSV:** {hsv2_h}°, {hsv2_s}%, {hsv2_v}%",
            inline=True
        )
        
        # Midpoint color info
        mid_r, mid_g, mid_b = hex_to_rgb(midpoint_hex)
        
        embed.add_field(
            name=f"Midpoint ({midpoint_hex})",
            value=f"**RGB:** {mid_r}, {mid_g}, {mid_b}\n"
                  f"**Blend:** 50/50 mix",
            inline=True
        )
        
        # Gradient properties
        color_distance = ((r2-r1)**2 + (g2-g1)**2 + (b2-b1)**2) ** 0.5
        brightness_diff = abs(get_color_brightness(r1, g1, b1) - get_color_brightness(r2, g2, b2))
        
        embed.add_field(
            name="Gradient Properties",
            value=f"**Color Distance:** {color_distance:.1f}\n"
                  f"**Brightness Diff:** {brightness_diff:.2f}\n"
                  f"**Transition:** {'Smooth' if color_distance < 200 else 'Bold'}",
            inline=True
        )
        
        # Set footer
        embed.set_footer(
            text=f"Gradient detected from {message.author.display_name}'s message • Horizontal gradient shown",
            icon_url=message.author.display_avatar.url if message.author.display_avatar else nextcord.Embed.Empty
        )
        embed.timestamp = nextcord.utils.utcnow()
        
        # Upload gradient as file and send embed
        filename = f"gradient_{hex_color1.lstrip('#')}_{hex_color2.lstrip('#')}.png"
        file = nextcord.File(gradient_swatch, filename=filename)
        embed.set_image(url=f"attachment://{filename}")
        
        await message.reply(embed=embed, file=file, mention_author=False)
        print(f"Sent gradient information for {hex_color1} → {hex_color2} in #{message.channel.name}")

    def _get_color_name(self, r: int, g: int, b: int) -> str:
        """Get a basic color name based on RGB values"""
        # Simple color name detection based on dominant channels
        if r > 200 and g < 100 and b < 100:
            return "Red"
        elif r < 100 and g > 200 and b < 100:
            return "Green"
        elif r < 100 and g < 100 and b > 200:
            return "Blue"
        elif r > 200 and g > 200 and b < 100:
            return "Yellow"
        elif r > 200 and g < 100 and b > 200:
            return "Magenta"
        elif r < 100 and g > 200 and b > 200:
            return "Cyan"
        elif r > 200 and g > 200 and b > 200:
            return "White"
        elif r < 50 and g < 50 and b < 50:
            return "Black"
        elif r > 100 and g > 100 and b > 100:
            return "Gray"
        elif r > 150 and g > 100 and b < 100:
            return "Orange"
        elif r > 100 and g < 100 and b > 150:
            return "Purple"
        else:
            return None

    async def _generate_contextual_response(self, content: str, context_type: str, original_message=None):
        """Generate a contextual response based on the trigger type"""
        # This helper method could be expanded for different response types
        # For now, we'll use the enhanced generate_notes function
        
        context_prompt = content
        if context_type == "reply" and original_message:
            context_prompt = f"User is replying to a previous message. Original context: '{original_message.content[:200]}...' User's reply: '{content}'"
        elif context_type == "mention":
            context_prompt = f"User mentioned the bot directly with: '{content}'"
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, generate_notes, context_prompt, True)


def setup(bot):
    bot.add_cog(Say(bot))
    print("SayCog has been added to the bot.")