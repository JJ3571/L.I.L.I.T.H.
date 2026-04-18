import nextcord
from nextcord import SlashOption, ui
from nextcord.ext import commands
import datetime, time, re, asyncio
import unicodedata

from main_bot.server_configs.config import GUILD_ID
from main_bot.server_configs.config import voice_channel_ids, create_fireteam_channel_id, seen_category_id, hidden_category_id, league_channel_id

class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reserved_channels = {}  # channel_id: timestamp when reservation ends
        print("Initializing VoiceCog.")

    def cog_unload(self):
        print("VoiceCog has been unloaded.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        if guild.id != GUILD_ID:
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            print(f"Categories not found in guild '{guild.name}'.")
            return

        # User joins the create_fireteam channel
        if after.channel and after.channel.id == create_fireteam_channel_id:
            print(f"{member.name} has joined the create_fireteam channel.")
            # Move a voice channel from hidden_category to seen_category
            moved_channel = None
            for channel_id in voice_channel_ids:
                channel = guild.get_channel(channel_id)
                if channel and channel.category and channel.category.id == hidden_category_id:
                    overwrites = channel.overwrites
                    # Allow @everyone to view the channel
                    overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
                    await channel.edit(category=seen_category, overwrites=overwrites)
                    moved_channel = channel
                    print(f"Moved '{channel.name}' to seen category and updated permissions.")
                    break  # Move only one channel

            if moved_channel:
                # Move the member to the newly moved channel
                await member.move_to(moved_channel)
                print(f"Moved {member.name} to '{moved_channel.name}'.")

        # Handle channels becoming empty or occupied
        if before.channel and before.channel.id in voice_channel_ids:
            if len(before.channel.members) == 0:
                reservation_end_time = self.reserved_channels.get(before.channel.id)
                if reservation_end_time and time.time() < reservation_end_time.timestamp():
                    print(f"Channel '{before.channel.name}' is reserved until {reservation_end_time}.")
                else:
                    await self.hide_channel(before.channel)
                    self.reserved_channels.pop(before.channel.id, None)
            else:
                self.reserved_channels.pop(before.channel.id, None)
        # Removes the reservation time when another user joins. May be useful in the future.
        # if after.channel and after.channel.id in voice_channel_ids:
        #     self.reserved_channels.pop(after.channel.id, None)

    async def hide_channel(self, channel):
        guild = channel.guild
        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            print(f"Hidden category not found in guild '{guild.name}'.")
            return

        overwrites = channel.overwrites
        # Deny @everyone the permission to view the channel
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
        await channel.edit(category=hidden_category, overwrites=overwrites)
        print(f"Moved '{channel.name}' to hidden category and updated permissions.")

    @nextcord.slash_command(name="voice", description="Voice channel management commands.",guild_ids=[GUILD_ID])
    async def voice(self, interaction: nextcord.Interaction):
        pass

    import unicodedata

    @voice.subcommand(name="tidy_up", description="Manually tidy up voice channels.")
    async def tidy_up(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild.id != GUILD_ID: # This check might be redundant if command is guild_ids restricted
            await interaction.followup.send("Command not applicable in this guild.", ephemeral=True)
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not hidden_category or not seen_category:
            await interaction.followup.send("Required voice categories not found.", ephemeral=True)
            print("Categories not found during tidy_up command.")
            return

        tidied_messages = []

        # 1. Original tidy-up for pre-defined voice_channel_ids
        moved_to_hidden_count = 0
        for channel_id in voice_channel_ids:
            channel = guild.get_channel(channel_id)
            # Ensure it's a voice channel and in the seen category before hiding
            if isinstance(channel, nextcord.VoiceChannel) and channel.category and channel.category.id == seen_category_id:
                await self.hide_channel(channel)
                moved_to_hidden_count += 1
        if moved_to_hidden_count > 0:
            tidied_messages.append(f"Moved {moved_to_hidden_count} standard channel(s) to hidden category.")
            print(f"Tidy_up: Moved {moved_to_hidden_count} standard channels to hidden.")

        # 2. Legacy cleanup for v1/v2 temp waterboard channels (DB); v3 (WaterboardCog3) uses fixed channels only.
        waterboard_cog = self.bot.get_cog('WaterboardCog3')
        if waterboard_cog and hasattr(waterboard_cog, 'get_temp_channels') and hasattr(
            waterboard_cog, 'delete_temp_channel'
        ):
            print("Tidy_up: Found waterboard cog with temp-channel DB. Proceeding with waterboard channel cleanup.")
            try:
                # Ensure the cog has its tables created if it hasn't already
                if hasattr(waterboard_cog, 'create_tables') and not hasattr(waterboard_cog, '_tables_created'):
                     if hasattr(waterboard_cog, 'create_tables'): # Check if method exists
                        await waterboard_cog.create_tables()
                        waterboard_cog._tables_created = True # Set flag after creation
                        print("Tidy_up: Ensured waterboard cog tables are created.")

                temp_wb_channel_ids = await waterboard_cog.get_temp_channels()
                deleted_wb_discord_channels = 0
                deleted_wb_db_entries = 0

                if temp_wb_channel_ids:
                    print(f"Tidy_up: Waterboard DB lists channels: {temp_wb_channel_ids}")
                    for wb_channel_id in list(temp_wb_channel_ids):  # Iterate over a copy
                        channel_to_delete = guild.get_channel(wb_channel_id) # Use guild.get_channel
                        if channel_to_delete and isinstance(channel_to_delete, nextcord.VoiceChannel):
                            print(f"Tidy_up: Attempting to delete Discord waterboard channel: {channel_to_delete.name} ({wb_channel_id})")
                            try:
                                await channel_to_delete.delete(reason="Tidy Up command (Waterboard DB)")
                                deleted_wb_discord_channels += 1
                            except nextcord.errors.NotFound:
                                print(f"Tidy_up: Waterboard channel {wb_channel_id} already deleted from Discord.")
                            except Exception as e:
                                print(f"Tidy_up: Error deleting waterboard channel {wb_channel_id} from Discord: {e}")
                        else:
                            print(f"Tidy_up: Waterboard channel {wb_channel_id} from DB not found on Discord or not a voice channel.")
                        
                        # Always attempt to remove from Waterboard DB
                        await waterboard_cog.delete_temp_channel(wb_channel_id)
                        deleted_wb_db_entries += 1
                    
                    if deleted_wb_discord_channels > 0 or deleted_wb_db_entries > 0:
                        tidied_messages.append(
                            f"Waterboard: Deleted {deleted_wb_discord_channels} Discord channel(s) "
                            f"and removed {deleted_wb_db_entries} DB entries."
                        )
                    print(f"Tidy_up: Waterboard cleanup complete. Deleted {deleted_wb_discord_channels} Discord channels, removed {deleted_wb_db_entries} DB entries.")
                else:
                    print("Tidy_up: No waterboard channels found in the waterboard cog's database.")
            except Exception as e:
                print(f"Tidy_up: An error occurred during waterboard channel cleanup: {e}")
                tidied_messages.append("An error occurred during waterboard channel cleanup.")
        elif waterboard_cog:
            print("Tidy_up: Waterboard v3 loaded; skipping legacy temp-channel DB cleanup.")
        else:
            print("Tidy_up: Waterboard cog not found. Skipping legacy waterboard DB cleanup.")
            # tidied_messages.append("Waterboard cog not found for specific cleanup.")


        # 3. Original generic cleanup for channels with "💧" in their name
        # This catches any "💧" channels missed or if the waterboard cog wasn't available.
        print("Tidy_up: Proceeding with generic temporary channel cleanup by name (Channels with waterdrop emoji').")
        generic_deleted_count = 0
        # Fetch a fresh list of voice channels as some might have been deleted above
        current_voice_channels = guild.voice_channels 
        for channel in current_voice_channels:
            if "💧" in channel.name:  # From original waterboard.py and your tidy_up
                channel_name_safe = channel.name.encode('ascii', 'ignore').decode('ascii')
                print(f"Tidy_up (name check): Deleting channel: {channel_name_safe}")
                try:
                    await channel.delete(reason="Tidy Up command (name match '💧')")
                    generic_deleted_count += 1
                except nextcord.errors.NotFound:
                    print(f"Tidy_up (name check): Channel {channel_name_safe} was already deleted.")
                except Exception as e:
                    print(f"Tidy_up (name check): Error deleting channel {channel_name_safe}: {e}")
        
        if generic_deleted_count > 0:
            tidied_messages.append(f"Generic: Deleted {generic_deleted_count} channel(s) by name (e.g., containing '💧').")
        print(f"Tidy_up: Generic name-based cleanup deleted {generic_deleted_count} channels.")

        if not tidied_messages:
            final_message = "Voice channels tidied up. No specific actions taken for listed types."
        else:
            final_message = "Voice channels tidied up:\n- " + "\n- ".join(tidied_messages)

        await interaction.followup.send(final_message, ephemeral=True)
        print(f"Tidy_up: {interaction.user.name} ran tidy_up command.")

    @voice.subcommand(name="reserve_channel", description="Reserve a voice channel for a set amount of time.")
    async def reserve_channel(
        self,
        interaction: nextcord.Interaction,
        duration: int,
        unit: str = SlashOption(
            name="unit",
            description="Select the time unit",
            choices={"minutes": "minutes", "hours": "hours"}
        )
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        channel_id = interaction.channel_id
        channel = guild.get_channel(channel_id)
        if not channel or channel.id not in voice_channel_ids:
            await interaction.followup.send("Invalid channel ID.", ephemeral=True)
            return

        if unit == "minutes":
            reservation_time = datetime.datetime.now() + datetime.timedelta(minutes=duration)
            delay = duration * 60
        elif unit == "hours":
            reservation_time = datetime.datetime.now() + datetime.timedelta(hours=duration)
            delay = duration * 3600
        else:
            await interaction.followup.send("Invalid time unit. Use 'minutes' or 'hours'.", ephemeral=True)
            return

        self.reserved_channels[channel_id] = reservation_time
        await interaction.followup.send(f"Reserved channel {channel.name} for {duration} {unit}.", ephemeral=True)
        print(f"{interaction.user.name} reserved channel {channel.name} for {duration} {unit}.")

        # Schedule the task to move the channel after the specified duration
        asyncio.create_task(self.move_channel_to_hidden(guild, channel, delay))

    async def move_channel_to_hidden(self, guild, channel, delay):
        await asyncio.sleep(delay)
        hidden_category = guild.get_channel(hidden_category_id)
        if hidden_category:
            await channel.edit(category=hidden_category)
            print(f"Moved channel {channel.name} to hidden category after reservation time.")

    @voice.subcommand(name="create_temp_channel", description="Create a temporary voice channel with a custom name.")
    async def create_temp_channel(self, interaction: nextcord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        if not re.match(r'^[\w-]+$', name):
            await interaction.followup.send("Invalid channel name. Use only letters, numbers, hyphens, and underscores.", ephemeral=True)
            return

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            await interaction.followup.send("Seen category not found.", ephemeral=True)
            return

        temp_channel = await guild.create_voice_channel(name, category=seen_category)
        await interaction.followup.send(f"Created temporary voice channel: {name}", ephemeral=True)
        print(f"{interaction.user.name} created temporary voice channel: {name}")

        def check_empty_channel(channel):
            return len(channel.members) == 0

        while True:
            await asyncio.sleep(10)
            if check_empty_channel(temp_channel):
                await temp_channel.delete()
                print(f"Deleted temporary voice channel: {name}")
                break

    @voice.subcommand(name="league", description="Pull the league channel out of the hidden category.")
    async def league(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        league_channel = guild.get_channel(league_channel_id)
        if not league_channel:
            await interaction.followup.send("League channel not found.", ephemeral=True)
            return

        seen_category = nextcord.utils.get(guild.categories, id=seen_category_id)
        if not seen_category:
            await interaction.followup.send("Seen category not found.", ephemeral=True)
            return

        overwrites = league_channel.overwrites
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
        await league_channel.edit(category=seen_category, overwrites=overwrites)
        await interaction.followup.send("League channel has been moved to the seen category.", ephemeral=True)
        print(f"League channel '{league_channel.name}' moved to seen category.")


    @voice.subcommand(name="select_channel", description="Select a channel to retrieve from the hidden category.")
    async def select_channel(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild.id != GUILD_ID:
            return

        hidden_category = nextcord.utils.get(guild.categories, id=hidden_category_id)
        if not hidden_category:
            await interaction.followup.send("Hidden category not found.", ephemeral=True)
            return

        class ChannelSelectView(nextcord.ui.View):
            def __init__(self, cog, interaction):
                super().__init__(timeout=60)
                self.cog = cog
                self.interaction = interaction

            async def on_timeout(self):
                await self.interaction.followup.send("Channel selection timed out.", ephemeral=True)

            @nextcord.ui.button(label="Cancel", style=nextcord.ButtonStyle.danger)
            async def cancel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
                await interaction.response.send_message("Channel selection cancelled.", ephemeral=True)
                self.stop()

        view = ChannelSelectView(self, interaction)

        for channel_id in voice_channel_ids:
            channel = guild.get_channel(channel_id)
            if channel and channel.category and channel.category.id == hidden_category_id:
                button = nextcord.ui.Button(label=channel.name, style=nextcord.ButtonStyle.primary)

                async def button_callback(interaction: nextcord.Interaction, channel=channel, view=view):
                    overwrites = channel.overwrites
                    overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=True)
                    await channel.edit(category=nextcord.utils.get(guild.categories, id=seen_category_id), overwrites=overwrites)
                    await interaction.response.send_message(f"Moved '{channel.name}' to seen category.", ephemeral=True)
                    view.stop()

                button.callback = button_callback
                view.add_item(button)

        await interaction.followup.send("Select a channel to receive from the hidden category:", view=view, ephemeral=True)

async def setup(bot):
    bot.add_cog(VoiceCog(bot))
    print("VoiceCog has been added to the bot.")