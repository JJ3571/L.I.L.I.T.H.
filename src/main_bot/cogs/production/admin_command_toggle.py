import nextcord
from nextcord.ext import commands
from nextcord import slash_command, SlashOption
import logging
from typing import Optional

from main_bot.server_configs.config import GUILD_ID
from main_bot.utils.admin_command_manager import admin_command_manager

logger = logging.getLogger(__name__)

class AdminCommandToggle(commands.Cog):
    """Manage visibility of admin commands"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("AdminCommandToggle initialized")
    
    @slash_command(guild_ids=[GUILD_ID], name="admin_toggle")
    async def admin_toggle(
        self,
        interaction: nextcord.Interaction,
        action: str = SlashOption(
            description="Action to perform",
            choices=["enable", "disable", "list", "reload"],
            required=True
        ),
        cog: str = SlashOption(
            description="Cog to manage",
            choices=["CraftyController", "ExampleAdminCog"],
            required=False,
            default="CraftyController"
        ),
        command: str = SlashOption(
            description="Specific command to toggle",
            required=False,
            default=None,
            autocomplete=True
        )
    ):
        """Toggle admin command visibility"""
        # Check if user has admin permissions first (before any async operations)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
        
        # Now defer for longer operations
        await interaction.response.defer(ephemeral=True)
        
        if action == "list":
            await self._list_commands(interaction, cog)
        elif action == "enable":
            await self._enable_command(interaction, cog, command)
        elif action == "disable":
            await self._disable_command(interaction, cog, command)
        elif action == "reload":
            await self._reload_commands(interaction, cog)
    
    async def _list_commands(self, interaction: nextcord.Interaction, cog: str):
        """List all admin commands and their status"""
        commands_status = admin_command_manager.get_all_admin_commands(cog)
        
        if not commands_status:
            await interaction.followup.send(f"❌ No admin commands found for cog: {cog}", ephemeral=True)
            return
        
        embed = nextcord.Embed(
            title=f"🔧 Admin Commands - {cog}",
            description="Current visibility status of admin commands",
            color=0x0099ff,
            timestamp=interaction.created_at
        )
        
        enabled_commands = []
        disabled_commands = []
        
        for cmd, enabled in commands_status.items():
            desc = admin_command_manager.get_command_description(cog, cmd)
            if enabled:
                enabled_commands.append(f"✅ `/{cmd}` - {desc}")
            else:
                disabled_commands.append(f"❌ `/{cmd}` - {desc}")
        
        if enabled_commands:
            embed.add_field(
                name="🟢 Enabled Commands",
                value="\n".join(enabled_commands),
                inline=False
            )
        
        if disabled_commands:
            embed.add_field(
                name="🔴 Disabled Commands", 
                value="\n".join(disabled_commands),
                inline=False
            )
        
        embed.add_field(
            name="💡 Usage",
            value="Use `/admin_toggle enable/disable` to toggle commands (auto-applies changes)\n"
                  "Use `/admin_toggle reload` for manual reload if needed",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _enable_command(self, interaction: nextcord.Interaction, cog: str, command: str):
        """Enable a specific admin command"""
        if not command:
            await interaction.followup.send("❌ Please specify a command to enable.", ephemeral=True)
            return
        
        # Remove prefix if provided
        command = command.lstrip('/')
        
        success = admin_command_manager.enable_command(cog, command)
        
        if success:
            # Auto-reload the cog to apply changes
            reload_success = await self._reload_cog(cog)
            
            if reload_success:
                embed = nextcord.Embed(
                    title="✅ Command Enabled & Applied",
                    description=f"Command `/{command}` has been enabled for {cog} and is now available!",
                    color=0x00ff00,
                    timestamp=interaction.created_at
                )
            else:
                embed = nextcord.Embed(
                    title="⚠️ Command Enabled (Reload Failed)",
                    description=f"Command `/{command}` has been enabled for {cog}, but auto-reload failed.\n"
                               f"Use `/admin_toggle reload` to apply changes manually.",
                    color=0xff9900,
                    timestamp=interaction.created_at
                )
        else:
            embed = nextcord.Embed(
                title="ℹ️ Command Already Enabled",
                description=f"Command `/{command}` is already enabled for {cog}.",
                color=0xffaa00,
                timestamp=interaction.created_at
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _disable_command(self, interaction: nextcord.Interaction, cog: str, command: str):
        """Disable a specific admin command"""
        if not command:
            await interaction.followup.send("❌ Please specify a command to disable.", ephemeral=True)
            return
        
        # Remove prefix if provided
        command = command.lstrip('/')
        
        success = admin_command_manager.disable_command(cog, command)
        
        if success:
            # Auto-reload the cog to apply changes
            reload_success = await self._reload_cog(cog)
            
            if reload_success:
                embed = nextcord.Embed(
                    title="🔴 Command Disabled & Applied",
                    description=f"Command `/{command}` has been disabled for {cog} and is no longer visible.",
                    color=0xff6600,
                    timestamp=interaction.created_at
                )
            else:
                embed = nextcord.Embed(
                    title="⚠️ Command Disabled (Reload Failed)",
                    description=f"Command `/{command}` has been disabled for {cog}, but auto-reload failed.\n"
                               f"Use `/admin_toggle reload` to apply changes manually.",
                    color=0xff9900,
                    timestamp=interaction.created_at
                )
        else:
            embed = nextcord.Embed(
                title="ℹ️ Command Already Disabled",
                description=f"Command `/{command}` is already disabled for {cog}.",
                color=0xffaa00,
                timestamp=interaction.created_at
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _reload_cog(self, cog: str) -> bool:
        """Helper method to reload a cog. Returns True if successful."""
        try:
            # Find the cog instance
            cog_instance = self.bot.get_cog(cog)
            if not cog_instance:
                logger.error(f"Cog {cog} not found for reload")
                return False
            
            # Get the module name
            module_name = cog_instance.__module__
            
            # Reload the cog (not awaited as reload_extension is not async)
            self.bot.reload_extension(module_name)
            logger.info(f"Successfully auto-reloaded cog {cog}")
            return True
            
        except Exception as e:
            logger.error(f"Error auto-reloading cog {cog}: {e}")
            return False
    
    async def _reload_commands(self, interaction: nextcord.Interaction, cog: str):
        """Reload the specified cog to apply command changes"""
        try:
            # Find the cog instance
            cog_instance = self.bot.get_cog(cog)
            if not cog_instance:
                await interaction.followup.send(f"❌ Cog {cog} not found.", ephemeral=True)
                return
            
            # Get the module name
            module_name = cog_instance.__module__
            
            # Reload the cog (not awaited as reload_extension is not async)
            self.bot.reload_extension(module_name)
            
            embed = nextcord.Embed(
                title="🔄 Commands Reloaded",
                description=f"Successfully reloaded {cog} with updated command visibility.\n\n"
                           f"All command changes have been applied!",
                color=0x0099ff,
                timestamp=interaction.created_at
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"Reloaded cog {cog} to apply admin command changes")
            
        except Exception as e:
            logger.error(f"Error reloading cog {cog}: {e}")
            await interaction.followup.send(f"❌ Error reloading {cog}: {str(e)}", ephemeral=True)
    
    @admin_toggle.on_autocomplete("command")
    async def command_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for command names"""
        try:
            print(f"[AUTOCOMPLETE] Function called with current: '{current}'")
            
            # Get the cog parameter from the interaction options
            cog_name = "CraftyController"  # Default
            if hasattr(interaction, 'data') and 'options' in interaction.data:
                for option in interaction.data['options']:
                    if option['name'] == 'cog' and 'value' in option:
                        cog_name = option['value']
                        break
            
            print(f"[AUTOCOMPLETE] Using cog: {cog_name}")
            logger.info(f"Autocomplete requested for cog: {cog_name}, current input: '{current}'")
            
            # Get all available commands
            all_commands = admin_command_manager.get_all_admin_commands(cog_name)
            print(f"[AUTOCOMPLETE] Available commands: {all_commands}")
            logger.info(f"Available commands for {cog_name}: {all_commands}")
            
            # Filter commands based on current input
            choices = []
            for cmd in all_commands.keys():
                if not current or current.lower() in cmd.lower():
                    # The choice needs to return the actual command name, not the display name
                    choices.append(cmd)
            
            print(f"[AUTOCOMPLETE] Sending choices: {choices}")
            logger.info(f"Autocomplete choices: {choices}")
            
            # Limit to 25 choices (Discord's limit)
            if not interaction.response.is_done():
                await interaction.response.send_autocomplete(choices[:25])
            
        except Exception as e:
            print(f"[AUTOCOMPLETE] Error: {e}")
            logger.error(f"Error in command_autocomplete: {e}")
            # Send empty list on error to prevent command failure
            if not interaction.response.is_done():
                await interaction.response.send_autocomplete([])

def setup(bot):
    bot.add_cog(AdminCommandToggle(bot))