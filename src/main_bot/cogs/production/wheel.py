import nextcord
from nextcord.ext import commands
import random
import asyncio

from main_bot.server_configs.config import GUILD_ID


class WheelModal(nextcord.ui.Modal):
    """Modal for inputting wheel values."""
    def __init__(self, parent_view):
        super().__init__(title="Wheel Spinner - Enter Values")
        self.parent_view = parent_view

        self.values_input = nextcord.ui.TextInput(
            label="Enter values (comma separated)",
            style=nextcord.TextInputStyle.paragraph,
            placeholder="Example: Alice, Bob, Charlie, Option 1, Option 2",
            min_length=3,
            max_length=1000,
            required=True
        )
        self.add_item(self.values_input)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            # Parse comma-separated values and clean them up
            raw_values = self.values_input.value.split(',')
            values = [value.strip() for value in raw_values if value.strip()]
            
            if len(values) < 2:
                await interaction.response.send_message(
                    "Please enter at least 2 values separated by commas.", 
                    ephemeral=True
                )
                return
            
            if len(values) > 20:
                await interaction.response.send_message(
                    "Please enter no more than 20 values for better display.", 
                    ephemeral=True
                )
                return
            
            # Initialize the wheel with the values
            await self.parent_view.initialize_wheel(interaction, values)
            
        except Exception as e:
            print(f"Error in WheelModal callback: {e}")
            await interaction.response.send_message(
                "An error occurred processing your values.", 
                ephemeral=True
            )


class WheelSpinView(nextcord.ui.View):
    """View for the wheel spinning interface."""
    def __init__(self, user_id, values):
        super().__init__(timeout=300.0)  # 5 minute timeout
        self.user_id = user_id
        self.remaining_values = values.copy()
        self.selected_values = []  # Track order of selection
        self.is_spinning = False

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This is not your wheel! Use `/wheel` to create your own.", 
                ephemeral=True
            )
            return False
        return True

    def create_wheel_embed(self, spinning=False, last_selected=None):
        """Create the wheel display embed."""
        if spinning:
            title = "🎡 Wheel Spinning..."
            color = nextcord.Color.gold()
        elif not self.remaining_values:
            title = "Done!"
            color = nextcord.Color.green()
        else:
            title = "🎡 Wheel Spinner"
            color = nextcord.Color.blue()

        embed = nextcord.Embed(title=title, color=color)
        
        # Show remaining values on the wheel (only if there are values left)
        if self.remaining_values:
            remaining_text = "\n".join([f"• {value}" for value in self.remaining_values])
            embed.add_field(
                name=f"Values on Wheel ({len(self.remaining_values)})",
                value=remaining_text,
                inline=False
            )

        # Show selection history
        if self.selected_values:
            history_text = ""
            for i, value in enumerate(self.selected_values, 1):
                history_text += f"**{i}.** {value}\n"
            
            embed.add_field(
                name="Selection Order",
                value=history_text,
                inline=False
            )

        # Show last selected value prominently
        if last_selected:
            embed.add_field(
                name="🎯 Just Selected",
                value=f"**{last_selected}**",
                inline=False
            )

        # Add spinning animation effect
        if spinning:
            embed.set_footer(text="🎲 Rolling the wheel... 🎲")
        elif self.remaining_values:
            embed.set_footer(text="Click 'Spin Wheel' to select the next value!")
        else:
            embed.set_footer(text="All values have been selected from the wheel!")

        return embed

    @nextcord.ui.button(label="🎡 Spin Wheel", style=nextcord.ButtonStyle.primary)
    async def spin_wheel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.is_spinning:
            await interaction.response.send_message(
                "The wheel is already spinning! Please wait.", 
                ephemeral=True
            )
            return

        if not self.remaining_values:
            await interaction.response.send_message(
                "No more values left on the wheel!", 
                ephemeral=True
            )
            return

        self.is_spinning = True
        
        # Show spinning animation
        spinning_embed = self.create_wheel_embed(spinning=True)
        await interaction.response.edit_message(embed=spinning_embed, view=self)
        
        # Simulate wheel spinning with delay
        await asyncio.sleep(0.5)
        
        # Select random value
        selected_value = random.choice(self.remaining_values)
        self.remaining_values.remove(selected_value)
        self.selected_values.append(selected_value)
        
        # Update button state if no values left
        if not self.remaining_values:
            button.disabled = True
            button.label = "🎯 Wheel Complete"
            button.style = nextcord.ButtonStyle.success

        self.is_spinning = False
        
        # Show final result
        result_embed = self.create_wheel_embed(last_selected=selected_value)
        await interaction.edit_original_message(embed=result_embed, view=self)

    @nextcord.ui.button(label="🔄 Reset Wheel", style=nextcord.ButtonStyle.secondary)
    async def reset_wheel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if self.is_spinning:
            await interaction.response.send_message(
                "Cannot reset while the wheel is spinning!", 
                ephemeral=True
            )
            return

        # Reset to original state
        all_values = self.remaining_values + self.selected_values
        self.remaining_values = all_values.copy()
        self.selected_values = []
        
        # Re-enable spin button
        spin_button = self.children[0]  # First button is spin button
        spin_button.disabled = False
        spin_button.label = "🎡 Spin Wheel"
        spin_button.style = nextcord.ButtonStyle.primary
        
        reset_embed = self.create_wheel_embed()
        await interaction.response.edit_message(embed=reset_embed, view=self)

    async def on_timeout(self):
        # Disable all buttons when timeout occurs
        for item in self.children:
            item.disabled = True
        
        timeout_embed = nextcord.Embed(
            title="Wheel Expired",
            description="This wheel session has expired due to inactivity.",
            color=nextcord.Color.dark_grey()
        )
        
        try:
            # This might fail if the original interaction is too old
            await self.message.edit(embed=timeout_embed, view=self)
        except:
            pass  # Message might be deleted or interaction expired


class WheelSetupView(nextcord.ui.View):
    """Initial view for setting up the wheel."""
    def __init__(self, user_id):
        super().__init__(timeout=180.0)  # 3 minute timeout for setup
        self.user_id = user_id

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This is not your wheel setup! Use `/wheel` to create your own.", 
                ephemeral=True
            )
            return False
        return True

    async def initialize_wheel(self, interaction: nextcord.Interaction, values):
        """Initialize the wheel with the provided values."""
        wheel_view = WheelSpinView(self.user_id, values)
        initial_embed = wheel_view.create_wheel_embed()
        
        await interaction.response.edit_message(embed=initial_embed, view=wheel_view)
        self.stop()  # Stop this setup view

    @nextcord.ui.button(label="📝 Enter Values", style=nextcord.ButtonStyle.primary)
    async def enter_values(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        modal = WheelModal(self)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        timeout_embed = nextcord.Embed(
            title="Setup Expired",
            description="Wheel setup has expired. Use `/wheel` to try again.",
            color=nextcord.Color.dark_grey()
        )
        
        try:
            await self.message.edit(embed=timeout_embed, view=None)
        except:
            pass


class VoiceChannelWheelView(nextcord.ui.View):
    """View for selecting which voice channel members to include in the wheel."""
    def __init__(self, user_id, members, channel_name):
        super().__init__(timeout=300.0)  # 5 minute timeout
        self.user_id = user_id
        self.all_members = members
        self.selected_members = members.copy()  # Start with all members selected
        self.channel_name = channel_name
        
        # Add toggle buttons for each member (max 20 members due to Discord limits)
        for i, member in enumerate(self.all_members):
            if i >= 20:  # Discord has a 25 component limit per view
                break
            button = nextcord.ui.Button(
                label=member.display_name,
                style=nextcord.ButtonStyle.success,  # Green = selected
                custom_id=f"member_{member.id}",
                row=i // 5  # 5 buttons per row
            )
            button.callback = self.create_member_toggle_callback(member)
            self.add_item(button)
    
    def create_member_toggle_callback(self, member):
        """Create a callback function for toggling member selection."""
        async def member_toggle_callback(interaction: nextcord.Interaction):
            if member in self.selected_members:
                # Remove member from selection
                self.selected_members.remove(member)
                # Update button to show deselected state
                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == f"member_{member.id}":
                        item.style = nextcord.ButtonStyle.secondary  # Gray = deselected
                        break
            else:
                # Add member to selection
                self.selected_members.append(member)
                # Update button to show selected state
                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == f"member_{member.id}":
                        item.style = nextcord.ButtonStyle.success  # Green = selected
                        break
            
            # Update the embed
            embed = self.create_selection_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        
        return member_toggle_callback

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This is not your wheel setup! Use `/wheelvc` to create your own.", 
                ephemeral=True
            )
            return False
        return True

    def create_selection_embed(self):
        """Create the member selection embed."""
        embed = nextcord.Embed(
            title="🎡 Voice Channel Wheel Setup",
            description=f"**From Voice Channel:** {self.channel_name}\n\nClick members to toggle their participation:",
            color=nextcord.Color.blue()
        )
        
        # Show selected members
        if self.selected_members:
            selected_names = [member.display_name for member in self.selected_members]
            embed.add_field(
                name=f"✅ Selected Members ({len(self.selected_members)})",
                value=", ".join(selected_names),
                inline=False
            )
        else:
            embed.add_field(
                name="✅ Selected Members (0)",
                value="*No members selected*",
                inline=False
            )
        
        # Show deselected members
        deselected_members = [member for member in self.all_members if member not in self.selected_members]
        if deselected_members:
            deselected_names = [member.display_name for member in deselected_members]
            embed.add_field(
                name=f"❌ Not Participating ({len(deselected_members)})",
                value=", ".join(deselected_names),
                inline=False
            )
        
        embed.set_footer(text="Green buttons = participating, Gray buttons = not participating")
        return embed

    @nextcord.ui.button(label="🎡 Create Wheel", style=nextcord.ButtonStyle.primary, row=4)
    async def create_wheel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if len(self.selected_members) < 2:
            await interaction.response.send_message(
                "You need at least 2 members selected to create a wheel!",
                ephemeral=True
            )
            return
        
        # Convert members to names for the wheel
        member_names = [member.display_name for member in self.selected_members]
        
        # Create the wheel view
        wheel_view = WheelSpinView(self.user_id, member_names)
        initial_embed = wheel_view.create_wheel_embed()
        
        await interaction.response.edit_message(embed=initial_embed, view=wheel_view)
        self.stop()  # Stop this selection view

    @nextcord.ui.button(label="✅ Select All", style=nextcord.ButtonStyle.success, row=4)
    async def select_all(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.selected_members = self.all_members.copy()
        
        # Update all member buttons to selected state
        for item in self.children:
            if hasattr(item, 'custom_id') and item.custom_id.startswith('member_'):
                item.style = nextcord.ButtonStyle.success
        
        embed = self.create_selection_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @nextcord.ui.button(label="❌ Deselect All", style=nextcord.ButtonStyle.danger, row=4)
    async def deselect_all(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.selected_members = []
        
        # Update all member buttons to deselected state
        for item in self.children:
            if hasattr(item, 'custom_id') and item.custom_id.startswith('member_'):
                item.style = nextcord.ButtonStyle.secondary
        
        embed = self.create_selection_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        timeout_embed = nextcord.Embed(
            title="🎡 Setup Expired",
            description="Voice channel wheel setup has expired. Use `/wheelvc` to try again.",
            color=nextcord.Color.dark_grey()
        )
        
        try:
            await self.message.edit(embed=timeout_embed, view=None)
        except:
            pass


class Wheel(commands.Cog):
    """A cog for spinning wheels with custom values."""
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(
        name="wheel", 
        description="Create a spinning wheel with custom values",
        guild_ids=[GUILD_ID]
    )
    async def wheel_command(self, interaction: nextcord.Interaction):
        """Start the wheel creation process."""
        setup_embed = nextcord.Embed(
            title="Setup",
            description=(
                "**Instructions:**\n"
                "• Enter 2-20 values separated by commas\n"
                "• The wheel will randomly select them one by one\n"
                "• You can reset the wheel to start over"
            ),
            color=nextcord.Color.blue()
        )
        setup_embed.set_footer(text="Click the button below to start.")
        
        view = WheelSetupView(interaction.user.id)
        await interaction.response.send_message(embed=setup_embed, view=view)

    @nextcord.slash_command(
        name="wheelvc", 
        description="Create a spinning wheel from voice channel members",
        guild_ids=[GUILD_ID]
    )
    async def wheel_vc_command(
        self, 
        interaction: nextcord.Interaction,
        channel: nextcord.VoiceChannel = nextcord.SlashOption(
            description="Voice channel to get members from (defaults to your current channel)",
            required=False
        )
    ):
        """Create a wheel from voice channel members."""
        # If no channel specified, try to use the user's current voice channel
        if channel is None:
            if interaction.user.voice and interaction.user.voice.channel:
                channel = interaction.user.voice.channel
            else:
                await interaction.response.send_message(
                    "You must either specify a voice channel or be in a voice channel yourself!",
                    ephemeral=True
                )
                return
        
        # Get members from the voice channel (excluding bots)
        members = [member for member in channel.members if not member.bot]
        
        if len(members) < 2:
            await interaction.response.send_message(
                f"Voice channel **{channel.name}** needs at least 2 non-bot members to create a wheel!",
                ephemeral=True
            )
            return
        
        if len(members) > 20:
            await interaction.response.send_message(
                f"Voice channel **{channel.name}** has too many members ({len(members)}). Please use a channel with 20 or fewer members.",
                ephemeral=True
            )
            return
        
        # Create the voice channel member selection view
        view = VoiceChannelWheelView(interaction.user.id, members, channel.name)
        embed = view.create_selection_embed()
        
        await interaction.response.send_message(embed=embed, view=view)


def setup(bot):
    bot.add_cog(Wheel(bot))