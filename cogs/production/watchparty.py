import nextcord
from nextcord.ext import commands, tasks
import datetime, pytz
import asyncio
from asyncio import Semaphore

from server_configs.config import GUILD_ID
from server_configs.cogs_config import watch_party_channel_id, seen_category_id, hidden_category_id

WATCH_PARTY_CHECK_INTERVAL = 5  # In minutes
WATCH_PARTY_EVENT_TIME = datetime.time(hour=18, minute=15)  # 6:15 PM PST
WATCH_PARTY_AUTO_HIDE_TIMEOUT = datetime.timedelta(hours=3)  # 3 hours

class WatchPartyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reserved_channels = {}
        self.reservation_end_time = None
        
        # Rate limiting for voice moves
        self.voice_move_semaphore = Semaphore(2)  # Limit to 2 concurrent moves for safety
        self.move_delay = 0.5  # Default delay in seconds between moves
        
        print("Initializing WatchPartyCog.")
        self.monitor_watch_party.start()

    def cog_unload(self):
        self.monitor_watch_party.cancel()
        print("WatchPartyCog has been unloaded.")

    @tasks.loop(minutes=WATCH_PARTY_CHECK_INTERVAL)
    async def monitor_watch_party(self):
        print("Running monitor_watch_party task.")
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            print(f"Guild with ID {GUILD_ID} not found.")
            return

        watch_party_channel = guild.get_channel(watch_party_channel_id)
        if not watch_party_channel:
            print(f"Watch Party channel with ID {watch_party_channel_id} not found in guild '{guild.name}'.")
            return

        current_time = datetime.datetime.now(pytz.timezone('US/Pacific'))
        if current_time.weekday() == 6 and current_time.time() >= WATCH_PARTY_EVENT_TIME and watch_party_channel.category.id == hidden_category_id:
            seen_category = guild.get_channel(seen_category_id)
            await watch_party_channel.edit(category=seen_category)
            self.reservation_end_time = current_time + WATCH_PARTY_AUTO_HIDE_TIMEOUT
            overwrites = watch_party_channel.overwrites
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
            await watch_party_channel.edit(overwrites=overwrites)
            print(f"Watch Party channel '{watch_party_channel.name}' moved to seen category for the event and reserved until {self.reservation_end_time}.")

        if self.reservation_end_time and current_time < self.reservation_end_time:
            print(f"Watch Party channel '{watch_party_channel.name}' is reserved until {self.reservation_end_time}.")
            return

        if len(watch_party_channel.members) == 0:
            # Get message history using async iteration instead of deprecated flatten()
            messages = []
            async for message in watch_party_channel.history(limit=100):
                messages.append(message)
            last_message_time = max((message.created_at for message in messages), default=None)
            if last_message_time and (datetime.datetime.now(pytz.utc) - last_message_time) > WATCH_PARTY_AUTO_HIDE_TIMEOUT:
                hidden_category = guild.get_channel(hidden_category_id)
                await watch_party_channel.edit(category=hidden_category)
                print(f"Watch Party channel '{watch_party_channel.name}' moved back to hidden category due to inactivity.")

    @monitor_watch_party.before_loop
    async def before_monitor_watch_party(self):
        await self.bot.wait_until_ready()
        print("Bot is ready. Starting monitor_watch_party loop.")

    async def move_user_with_rate_limit(self, user: nextcord.Member, target_channel: nextcord.VoiceChannel, max_retries: int = 3):
        """
        Move a user to a voice channel with rate limiting and exponential backoff.
        """
        async with self.voice_move_semaphore:
            for attempt in range(max_retries):
                try:
                    await user.move_to(target_channel)
                    await asyncio.sleep(self.move_delay)
                    return True
                except nextcord.errors.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        wait_time = (2 ** attempt) * 0.5  # Exponential backoff: 0.5s, 1s, 2s
                        print(f"Rate limited moving {user.display_name}, waiting {wait_time}s (attempt {attempt + 1})")
                        await asyncio.sleep(wait_time)
                    elif e.status == 400:  # User likely disconnected
                        print(f"User {user.display_name} likely disconnected during move")
                        return False
                    else:
                        print(f"HTTP error moving {user.display_name}: {e}")
                        return False
                except Exception as e:
                    print(f"Unexpected error moving {user.display_name}: {e}")
                    return False
            
            print(f"Failed to move {user.display_name} after {max_retries} attempts")
            return False

    async def vacate_users_with_rate_limit(self, users: list, target_channel: nextcord.VoiceChannel):
        """
        Move multiple users to a target channel with rate limiting and progress tracking.
        """
        if not users:
            return []
            
        successful_moves = []
        failed_moves = []
        
        print(f"Starting vacate operation: moving {len(users)} users to {target_channel.name}")
        
        for i, user in enumerate(users, 1):
            # Check if user is still in a voice channel before attempting move
            if not user.voice or not user.voice.channel:
                print(f"User {user.display_name} is no longer in a voice channel, skipping...")
                failed_moves.append(user)
                continue
                
            print(f"Moving user {i}/{len(users)}: {user.display_name}")
            
            move_success = await self.move_user_with_rate_limit(user, target_channel)
            
            if move_success:
                successful_moves.append(user)
                print(f"✅ Successfully moved {user.display_name} to {target_channel.name}")
            else:
                failed_moves.append(user)
                print(f"❌ Failed to move {user.display_name}")
        
        return successful_moves, failed_moves

    @nextcord.slash_command(name="watchparty", description="Manage the watch party channel.",guild_ids=[GUILD_ID])
    async def watchparty(self, interaction: nextcord.Interaction):
        pass

    @watchparty.subcommand(name="show", description="Move the watch party channel to the seen category.")
    async def watchparty_show(self, interaction: nextcord.Interaction):
        guild = self.bot.get_guild(GUILD_ID)
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        seen_category = guild.get_channel(seen_category_id)

        if watch_party_channel and seen_category:
            await interaction.response.defer()
            await watch_party_channel.edit(category=seen_category)
            self.reservation_end_time = datetime.datetime.now(pytz.timezone('US/Pacific')) + WATCH_PARTY_AUTO_HIDE_TIMEOUT
            readable_time = self.reservation_end_time.strftime("%m/%d at %I:%M%p PST")
            readable_time = readable_time.replace("AM", "am").replace("PM", "pm")
            overwrites = watch_party_channel.overwrites
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
            await watch_party_channel.edit(overwrites=overwrites)
            await interaction.followup.send(f"{watch_party_channel.name} reserved until {readable_time}.")
        else:
            await interaction.response.send_message("Failed to move the channel. Please check the configuration.")

    @watchparty.subcommand(name="hide", description="Move the watch party channel to the hidden category.")
    async def watchparty_hide(self, interaction: nextcord.Interaction):
        guild = self.bot.get_guild(GUILD_ID)
        watch_party_channel = guild.get_channel(watch_party_channel_id)
        hidden_category = guild.get_channel(hidden_category_id)

        if watch_party_channel and hidden_category:
            await interaction.response.defer()
            await watch_party_channel.edit(category=hidden_category)
            self.reservation_end_time = None
            await interaction.followup.send(f"{watch_party_channel.name} has been hidden.")
        else:
            await interaction.response.send_message("Failed to move the channel. Please check the configuration.")

    @nextcord.slash_command(name="vacate", description="Move all users from one voice channel to another", guild_ids=[GUILD_ID])
    async def vacate(self, interaction: nextcord.Interaction, 
                     from_channel: nextcord.VoiceChannel = nextcord.SlashOption(name="from", description="The voice channel to move users from"),
                     to_channel: nextcord.VoiceChannel = nextcord.SlashOption(name="to", description="The voice channel to move users to")):
        
        # Validate channels exist and are different
        if from_channel == to_channel:
            embed = nextcord.Embed(
                title="Invalid Channels",
                description="The 'from' and 'to' channels cannot be the same.",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get users in the source channel (excluding bots)
        users_to_move = [member for member in from_channel.members if not member.bot]
        
        if not users_to_move:
            embed = nextcord.Embed(
                title="No Users to Move",
                description=f"There are no users in {from_channel.mention} to move.",
                color=nextcord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check bot permissions for both channels
        bot_member = interaction.guild.get_member(self.bot.user.id)
        
        if not from_channel.permissions_for(bot_member).move_members:
            embed = nextcord.Embed(
                title="Permission Error",
                description=f"I don't have permission to move members from {from_channel.mention}.",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        if not to_channel.permissions_for(bot_member).move_members:
            embed = nextcord.Embed(
                title="Permission Error", 
                description=f"I don't have permission to move members to {to_channel.mention}.",
                color=nextcord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Send initial response
        user_list = ", ".join([user.display_name for user in users_to_move[:5]])
        if len(users_to_move) > 5:
            user_list += f" and {len(users_to_move) - 5} others"
            
        embed = nextcord.Embed(
            title="Vacating Channel",
            description=f"Moving {len(users_to_move)} users from {from_channel.mention} to {to_channel.mention}...\n\nUsers: {user_list}",
            color=nextcord.Color.blue()
        )
        embed.add_field(name="Rate Limiting", value=f"Using {self.move_delay}s delay between moves", inline=False)
        await interaction.response.send_message(embed=embed)
        
        # Perform the move operation
        successful_moves, failed_moves = await self.vacate_users_with_rate_limit(users_to_move, to_channel)
        
        # Send completion message
        if successful_moves:
            success_list = ", ".join([user.display_name for user in successful_moves[:10]])
            if len(successful_moves) > 10:
                success_list += f" and {len(successful_moves) - 10} others"
        else:
            success_list = "None"
            
        if failed_moves:
            failed_list = ", ".join([user.display_name for user in failed_moves[:5]])
            if len(failed_moves) > 5:
                failed_list += f" and {len(failed_moves) - 5} others"
        else:
            failed_list = "None"
        
        # Determine embed color based on results
        if len(successful_moves) == len(users_to_move):
            embed_color = nextcord.Color.green()
            title = "Vacate Completed Successfully"
        elif successful_moves:
            embed_color = nextcord.Color.orange()
            title = "Vacate Partially Completed"
        else:
            embed_color = nextcord.Color.red()
            title = "Vacate Failed"
        
        completion_embed = nextcord.Embed(
            title=title,
            description=f"Vacate operation completed for {from_channel.mention} → {to_channel.mention}",
            color=embed_color
        )
        completion_embed.add_field(
            name=f"✅ Successfully Moved ({len(successful_moves)})",
            value=success_list,
            inline=False
        )
        if failed_moves:
            completion_embed.add_field(
                name=f"❌ Failed to Move ({len(failed_moves)})",
                value=failed_list,
                inline=False
            )
        
        await interaction.followup.send(embed=completion_embed)

    # @nextcord.slash_command(name="vacate-config", description="Configure the vacate command rate limiting", guild_ids=[GUILD_ID])
    # async def vacate_config(self, interaction: nextcord.Interaction,
    #                         delay: float = nextcord.SlashOption(name="delay", description="Delay in seconds between moves (0.1 - 5.0)", min_value=0.1, max_value=5.0)):
        
    #     # Check if user has administrator permissions
    #     if not interaction.user.guild_permissions.administrator:
    #         embed = nextcord.Embed(
    #             title="Permission Denied",
    #             description="Only administrators can configure the vacate command settings.",
    #             color=nextcord.Color.red()
    #         )
    #         await interaction.response.send_message(embed=embed, ephemeral=True)
    #         return
        
    #     old_delay = self.move_delay
    #     self.move_delay = delay
        
    #     embed = nextcord.Embed(
    #         title="Vacate Configuration Updated",
    #         description=f"Rate limiting delay updated from {old_delay}s to {delay}s",
    #         color=nextcord.Color.green()
    #     )
    #     embed.add_field(
    #         name="Impact",
    #         value=f"Each user move will now wait {delay} seconds, helping to avoid Discord rate limits.",
    #         inline=False
    #     )
        
    #     await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and before.channel.id == watch_party_channel_id:
            if len(before.channel.members) == 0:
                current_time = datetime.datetime.now(pytz.timezone('US/Pacific'))
                if not self.reservation_end_time or current_time >= self.reservation_end_time:
                    await self.hide_channel(before.channel)

    async def hide_channel(self, channel):
        guild = channel.guild
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            print(f"Hidden category not found in guild '{guild.name}'.")
            return

        overwrites = channel.overwrites
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
        await channel.edit(category=hidden_category, overwrites=overwrites)
        print(f"Moved '{channel.name}' to hidden category and updated permissions.")

async def setup(bot):
    bot.add_cog(WatchPartyCog(bot))
    print("WatchPartyCog has been added to the bot.")