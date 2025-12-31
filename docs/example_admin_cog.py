import nextcord
from nextcord.ext import commands
from nextcord import slash_command, SlashOption
from utils.admin_command_manager import admin_command_manager
from server_configs.config import GUILD_ID

def conditional_slash_command(*args, **kwargs):
    """Decorator that conditionally registers slash commands based on admin settings"""
    def decorator(func):
        command_name = func.__name__
        cog_name = "ExampleAdminCog"  # This cog's name
        
        if admin_command_manager.is_command_enabled(cog_name, command_name):
            return slash_command(*args, **kwargs)(func)
        else:
            # Create a dummy command object to handle autocomplete decorators
            class DummyCommand:
                def __init__(self, func):
                    self.func = func
                    self._disabled_admin_command = True
                
                def on_autocomplete(self, param_name):
                    """Dummy autocomplete decorator for disabled commands"""
                    def autocomplete_decorator(autocomplete_func):
                        return autocomplete_func
                    return autocomplete_decorator
                
                def __call__(self, *args, **kwargs):
                    return self.func(*args, **kwargs)
            
            return DummyCommand(func)
    return decorator

class ExampleAdminCog(commands.Cog):
    """Example cog demonstrating admin command toggle functionality"""
    
    def __init__(self, bot):
        self.bot = bot
    
    # Regular command - always visible
    @slash_command(guild_ids=[GUILD_ID])
    async def example_info(self, interaction: nextcord.Interaction):
        """Show information about this example cog (always visible)"""
        embed = nextcord.Embed(
            title="📋 Example Admin Cog",
            description="This cog demonstrates the admin command toggle system.",
            color=0x0099ff
        )
        
        embed.add_field(
            name="🟢 Always Visible",
            value="`/example_info` - This command\n`/example_status` - Show status",
            inline=False
        )
        
        embed.add_field(
            name="🔴 Toggleable Admin Commands",
            value="`/example_config` - Configuration command\n`/example_reset` - Reset command",
            inline=False
        )
        
        embed.add_field(
            name="💡 Try It",
            value="Use `/admin_toggle list cog:ExampleAdminCog` to see command states!",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Another regular command - always visible
    @slash_command(guild_ids=[GUILD_ID])
    async def example_status(self, interaction: nextcord.Interaction):
        """Show example cog status (always visible)"""
        embed = nextcord.Embed(
            title="✅ Example Cog Status",
            description="This cog is running normally!",
            color=0x00ff00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Admin command - toggleable visibility
    @conditional_slash_command(guild_ids=[GUILD_ID])
    async def example_config(
        self,
        interaction: nextcord.Interaction,
        setting: str = SlashOption(description="Configuration setting", required=True),
        value: str = SlashOption(description="Setting value", required=True)
    ):
        """Configure example cog settings (admin command)"""
        await interaction.response.send_message(
            f"🔧 Configuration updated: `{setting}` = `{value}`\n\n"
            f"*This is a toggleable admin command - it can be hidden when not needed!*",
            ephemeral=True
        )
    
    @example_config.on_autocomplete("setting")
    async def config_setting_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for configuration settings"""
        settings = ["debug_mode", "log_level", "auto_update", "notification_channel"]
        filtered = [s for s in settings if current.lower() in s.lower()]
        await interaction.response.send_autocomplete(filtered[:25])
    
    # Another admin command - toggleable visibility
    @conditional_slash_command(guild_ids=[GUILD_ID])
    async def example_reset(
        self,
        interaction: nextcord.Interaction,
        confirm: bool = SlashOption(description="Confirm reset action", required=True)
    ):
        """Reset example cog data (admin command)"""
        if not confirm:
            await interaction.response.send_message("❌ Reset cancelled. Set confirm=True to proceed.", ephemeral=True)
            return
        
        await interaction.response.send_message(
            "🔄 Example cog data has been reset!\n\n"
            "*This is another toggleable admin command - perfect for dangerous operations!*",
            ephemeral=True
        )

def setup(bot):
    bot.add_cog(ExampleAdminCog(bot))