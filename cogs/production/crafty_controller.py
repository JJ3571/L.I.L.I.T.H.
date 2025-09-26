import nextcord
from nextcord.ext import commands, tasks
from nextcord import slash_command, SlashOption
import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta
import json

from server_configs.config import CRAFTY_BASE_URL, CRAFTY_USERNAME, CRAFTY_PASSWORD, GUILD_ID, IS_DEVELOPMENT
from utils.crafty_api import CraftyAPI
from utils.crafty_automation import CraftyAutomationDB, ServerAutomationConfig
from utils.admin_command_manager import admin_command_manager

logger = logging.getLogger(__name__)

def conditional_slash_command(*args, **kwargs):
    """Decorator that conditionally registers slash commands based on admin settings"""
    def decorator(func):
        command_name = func.__name__
        if admin_command_manager.is_command_enabled("CraftyController", command_name):
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
                        # Just return the function unchanged
                        return autocomplete_func
                    return autocomplete_decorator
                
                def __call__(self, *args, **kwargs):
                    return self.func(*args, **kwargs)
            
            return DummyCommand(func)
    return decorator

def admin_only_check():
    """Check if user has administrator permissions"""
    def predicate(interaction: nextcord.Interaction):
        return interaction.user.guild_permissions.administrator
    return predicate

class RestartConfirmationView(nextcord.ui.View):
    """Confirmation view for restarting servers with active players"""
    
    def __init__(self, crafty_api, server_id: str, server_name: str, player_count: int):
        super().__init__(timeout=60.0)
        self.crafty_api = crafty_api
        self.server_id = server_id
        self.server_name = server_name
        self.player_count = player_count
        self.result = None
    
    @nextcord.ui.button(label="✅ Yes, Restart Server", style=nextcord.ButtonStyle.danger)
    async def confirm_restart(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        
        success = await self.crafty_api.restart_server(self.server_id)
        if success:
            embed = nextcord.Embed(
                title="🔄 Server Restarting",
                description=f"**{self.server_name}** is now restarting...\n\n"
                           f"⚠️ **{self.player_count}** player{'s' if self.player_count != 1 else ''} will be disconnected.\n"
                           f"This may take a few minutes.",
                color=0x0099ff,
                timestamp=interaction.created_at
            )
        else:
            embed = nextcord.Embed(
                title="❌ Restart Failed",
                description="Failed to restart server. Check Crafty Controller logs.",
                color=0xff0000,
                timestamp=interaction.created_at
            )
        
        # Disable all buttons and update the message  
        for item in self.children:
            item.disabled = True
        
        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()
    
    @nextcord.ui.button(label="❌ Cancel", style=nextcord.ButtonStyle.secondary)
    async def cancel_restart(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        embed = nextcord.Embed(
            title="✅ Restart Cancelled",
            description=f"Server restart cancelled. **{self.server_name}** will continue running.",
            color=0x00ff00,
            timestamp=interaction.created_at
        )
        
        # Disable all buttons and update the message
        for item in self.children:
            item.disabled = True
            
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
    
    async def on_timeout(self):
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True

class CraftyController(commands.Cog):
    """Discord cog for managing Minecraft servers via Crafty Controller"""
    
    def __init__(self, bot):
        self.bot = bot
        self.crafty_available = self._check_crafty_config()
        
        if self.crafty_available:
            self.crafty_api = CraftyAPI(CRAFTY_BASE_URL, CRAFTY_USERNAME, CRAFTY_PASSWORD)
            self.automation_db = CraftyAutomationDB()
            print(f"[CRAFTY] Initialized with URL: {CRAFTY_BASE_URL}")
            
            # Start automation tasks
            asyncio.create_task(self._init_automation())
        else:
            self.crafty_api = None
            self.automation_db = None
            print(f"[CRAFTY] Not available - missing configuration")
            
        self._servers_cache = {}
        self._cache_time = None
        
        # Add conditional automation subcommands
        if self.crafty_available:
            self.add_automation_subcommands()
    
    def _check_crafty_config(self) -> bool:
        """Check if Crafty Controller configuration is available and valid"""
        try:
            # Check if all required config values are set and not placeholder values
            if not CRAFTY_BASE_URL or "your-crafty-domain.com" in CRAFTY_BASE_URL:
                return False
            if not CRAFTY_USERNAME or CRAFTY_USERNAME in ["production_bot", "your-username"]:
                return False
            if not CRAFTY_PASSWORD or CRAFTY_PASSWORD in ["your-production-password", "your-password"]:
                return False
            return True
        except:
            return False
    
    def cog_unload(self):
        """Clean up when cog is unloaded"""
        if hasattr(self, 'automation_monitor') and self.automation_monitor.is_running():
            self.automation_monitor.cancel()
        if self.crafty_api:
            asyncio.create_task(self.crafty_api.close())
    
    async def _init_automation(self):
        """Initialize the automation system"""
        try:
            await self.automation_db.init_database()
            self.automation_monitor.start()
            logger.info("Crafty automation system started")
        except Exception as e:
            logger.error(f"Failed to initialize automation system: {e}")
    
    @tasks.loop(minutes=5)  # Check every 5 minutes
    async def automation_monitor(self):
        """Monitor servers for auto-shutdown conditions"""
        if not self.crafty_available:
            return
        
        try:
            monitored_servers = await self.automation_db.get_all_monitored_servers()
            current_time = datetime.now()
            
            for config in monitored_servers:
                try:
                    # Get current server stats
                    stats = await self.crafty_api.get_server_stats(config.server_id)
                    if not stats:
                        continue
                    
                    server_name = stats.get("server_id", {}).get("server_name", f"Server {config.server_id}")
                    is_running = stats.get("running", False)
                    player_count = stats.get("online", 0)
                    
                    if not is_running:
                        continue  # Skip offline servers
                    
                    if player_count > 0:
                        # Players online - update last seen time
                        await self.automation_db.update_last_player_seen(
                            config.server_id, 
                            current_time.isoformat()
                        )
                        logger.debug(f"[AUTO] {server_name}: {player_count} players online, updating last seen")
                        continue
                    
                    # No players online - check if we should shutdown
                    if config.last_player_seen:
                        last_seen = datetime.fromisoformat(config.last_player_seen)
                        idle_time = current_time - last_seen
                        timeout_delta = timedelta(minutes=config.idle_timeout_minutes)
                        
                        if idle_time >= timeout_delta:
                            # Time to shutdown
                            logger.info(f"[AUTO] Shutting down idle server: {server_name} (idle for {idle_time})")
                            success = await self.crafty_api.stop_server(config.server_id)
                            
                            if success:
                                # Notify in a designated channel if configured
                                await self._notify_auto_shutdown(server_name, idle_time)
                            else:
                                logger.error(f"[AUTO] Failed to shutdown server: {server_name}")
                        else:
                            remaining = timeout_delta - idle_time
                            logger.debug(f"[AUTO] {server_name}: idle for {idle_time}, {remaining} until shutdown")
                    else:
                        # First time seeing 0 players, set the timestamp
                        await self.automation_db.update_last_player_seen(
                            config.server_id,
                            current_time.isoformat()
                        )
                        logger.info(f"[AUTO] {server_name}: Started idle timer (0 players)")
                        
                except Exception as e:
                    logger.error(f"Error processing server {config.server_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error in automation monitor: {e}")
    
    @automation_monitor.before_loop
    async def before_automation_monitor(self):
        """Wait for bot to be ready before starting automation"""
        await self.bot.wait_until_ready()
    
    async def _notify_auto_shutdown(self, server_name: str, idle_time: timedelta):
        """Notify about automatic server shutdown"""
        try:
            # You can customize this to send to a specific channel
            # For now, just log it
            logger.info(f"[AUTO-SHUTDOWN] {server_name} automatically stopped after {idle_time} of inactivity")
        except Exception as e:
            logger.error(f"Error sending shutdown notification: {e}")
    
    async def _refresh_servers_cache(self, force: bool = False) -> bool:
        """Refresh the servers cache if needed"""
        if not self.crafty_available or not self.crafty_api:
            return False
            
        import time
        current_time = time.time()
        
        # Cache for 60 seconds unless forced
        if not force and self._cache_time and (current_time - self._cache_time) < 60:
            return True
        
        try:
            servers = await self.crafty_api.get_servers()
            if servers is not None:
                # Use server_id as key (which can be string UUID or integer)
                self._servers_cache = {str(server["server_id"]): server for server in servers}
                self._cache_time = current_time
                logger.info(f"Cached {len(servers)} servers")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to refresh servers cache: {e}")
            return False
    
    async def _get_server_choices(self, current: str = "") -> list:
        """Get server choices for autocomplete"""
        await self._refresh_servers_cache()
        choices = []
        
        for server_id, server in self._servers_cache.items():
            name = server.get("server_name", f"Server {server_id}")
            choice_text = f"{name} (ID: {server_id})"
            if current.lower() in choice_text.lower():
                choices.append(choice_text)
        
        return choices[:25]  # Discord limit
    
    def _parse_server_choice(self, choice: str) -> Optional[str]:
        """Parse server ID from autocomplete choice"""
        try:
            logger.info(f"Parsing server choice: '{choice}'")
            
            # Extract ID from "Server Name (ID: uuid-string)" format
            if "(ID: " in choice and choice.endswith(")"):
                id_part = choice.split("(ID: ")[1][:-1]
                logger.info(f"Extracted server ID: '{id_part}'")
                return id_part
            else:
                logger.warning(f"Choice format doesn't match expected pattern: '{choice}'")
                
        except Exception as e:
            logger.error(f"Error parsing server choice '{choice}': {e}")
            
        return None

    def _format_server_address(self, server_port: int) -> str:
        """Format the server address based on port"""
        if server_port == 25565:
            # Vanilla server gets its own dedicated domain
            return "vanilla.lif3gaming.gg"
        else:
            # All other servers use modded domain with port
            return f"modded.lif3gaming.gg:{server_port}"
    
    async def _check_crafty_available(self, interaction: nextcord.Interaction) -> bool:
        """Check if Crafty Controller is available and respond with error if not"""
        if not self.crafty_available:
            embed = nextcord.Embed(
                title="❌ Crafty Controller Unavailable",
                description="Crafty Controller integration is not configured for this environment.",
                color=0xff0000
            )
            if IS_DEVELOPMENT:
                embed.add_field(
                    name="Development Note",
                    value="Crafty Controller is only available on the local development network.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Production Note", 
                    value="Crafty Controller needs to be configured for production deployment.",
                    inline=False
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return False
        return True

    @conditional_slash_command(
        name="crafty_automation",
        description="Configure server automation settings",
        guild_ids=[GUILD_ID]
    )
    async def automation_config(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server",
            autocomplete=True,
            required=True
        ),
        auto_shutdown: bool = SlashOption(
            description="Enable auto-shutdown when idle",
            required=False,
            default=None
        ),
        idle_timeout: int = SlashOption(
            description="Minutes of 0 players before shutdown (5-180, default: 10)",
            required=False,
            default=None,
            min_value=5,
            max_value=180
        ),
        always_online: bool = SlashOption(
            description="Keep server online 24/7 (overrides auto-shutdown)",
            required=False,
            default=None
        )
    ):
        """Configure automation settings for a server"""
        await interaction.response.defer()
        
        if not await self._check_crafty_available(interaction):
            return
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        # Get current config
        config = await self.automation_db.get_server_config(server_id)
        server_name = server.split(" (ID:")[0] if " (ID:" in server else "Unknown Server"
        
        # Update settings if provided
        updated = False
        changes = []
        
        if auto_shutdown is not None:
            config.auto_shutdown_enabled = auto_shutdown
            changes.append(f"Auto-shutdown: {'✅ Enabled' if auto_shutdown else '❌ Disabled'}")
            updated = True
        
        if idle_timeout is not None:
            config.idle_timeout_minutes = idle_timeout
            changes.append(f"Idle timeout: {idle_timeout} minutes")
            updated = True
        
        if always_online is not None:
            config.always_online = always_online
            changes.append(f"Always online: {'✅ Yes' if always_online else '❌ No'}")
            updated = True
        
        # Save changes
        if updated:
            await self.automation_db.update_server_config(config)
        
        # Create response embed
        embed = nextcord.Embed(
            title="🤖 Server Automation Settings",
            color=0x00ff00 if updated else 0x0099ff,
            timestamp=interaction.created_at
        )
        
        embed.add_field(
            name="Server",
            value=server_name,
            inline=False
        )
        
        # Current settings
        status_icon = "🟢" if config.auto_shutdown_enabled and not config.always_online else "🔴"
        embed.add_field(
            name="🔧 Current Settings",
            value=f"**Auto-shutdown:** {'✅ Enabled' if config.auto_shutdown_enabled else '❌ Disabled'}\n"
                  f"**Idle timeout:** {config.idle_timeout_minutes} minutes\n"
                  f"**Always online:** {'✅ Yes' if config.always_online else '❌ No'}\n"
                  f"**Status:** {status_icon} {'Active' if config.auto_shutdown_enabled and not config.always_online else 'Inactive'}",
            inline=False
        )
        
        if changes:
            embed.add_field(
                name="✅ Changes Applied",
                value="\n".join(changes),
                inline=False
            )
        
        # Add helpful notes
        if config.always_online:
            embed.add_field(
                name="ℹ️ Note",
                value="Always online is enabled - this server will never auto-shutdown regardless of player count.",
                inline=False
            )
        elif config.auto_shutdown_enabled:
            embed.add_field(
                name="ℹ️ How it works",
                value=f"Server will automatically stop after {config.idle_timeout_minutes} minutes with 0 players online. "
                      f"Servers with active players are protected from shutdown.",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    
    @automation_config.on_autocomplete("server")
    async def automation_server_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection in automation config"""
        try:
            if not self.crafty_available:
                choices = ["Crafty Controller not available"]
            else:
                choices = await self._get_server_choices(current)
                if not choices:
                    choices = ["No servers found"]
            
            await interaction.response.send_autocomplete(choices)
        except Exception as e:
            logger.error(f"Error in automation autocomplete: {e}")
            try:
                await interaction.response.send_autocomplete(["Error loading servers"])
            except:
                pass

    @conditional_slash_command(
        name="crafty_automation_status",
        description="View automation status for all servers",
        guild_ids=[GUILD_ID]
    )
    async def automation_status(self, interaction: nextcord.Interaction):
        """View automation status for all servers"""
        await interaction.response.defer()
        
        if not await self._check_crafty_available(interaction):
            return
        
        # Get all servers with automation configured
        all_configs = []
        if self._servers_cache:
            for server_id in self._servers_cache.keys():
                config = await self.automation_db.get_server_config(server_id)
                if config.auto_shutdown_enabled or config.always_online:
                    all_configs.append(config)
        
        embed = nextcord.Embed(
            title="🤖 Server Automation Overview",
            color=0x0099ff,
            timestamp=interaction.created_at
        )
        
        if not all_configs:
            embed.description = "No servers have automation configured."
            embed.add_field(
                name="💡 Getting Started",
                value="Use `/crafty_automation` to configure auto-shutdown for your servers!",
                inline=False
            )
        else:
            active_count = sum(1 for c in all_configs if c.auto_shutdown_enabled and not c.always_online)
            always_on_count = sum(1 for c in all_configs if c.always_online)
            
            embed.description = f"**Active:** {active_count} servers • **Always Online:** {always_on_count} servers"
            
            for config in all_configs[:10]:  # Limit to 10 to avoid embed limits
                server_info = self._servers_cache.get(config.server_id, {})
                server_name = server_info.get("server_name", f"Server {config.server_id}")
                
                if config.always_online:
                    status = "🟡 Always Online"
                elif config.auto_shutdown_enabled:
                    status = f"🟢 Auto-shutdown ({config.idle_timeout_minutes}m)"
                else:
                    status = "🔴 Disabled"
                
                embed.add_field(
                    name=server_name,
                    value=status,
                    inline=True
                )
        
        await interaction.followup.send(embed=embed)

    # Parent command for the /crafty command group
    @nextcord.slash_command(name="crafty", description="Minecraft server management commands", guild_ids=[GUILD_ID])
    async def crafty_parent(self, interaction: nextcord.Interaction):
        """Parent command for Crafty Controller - use subcommands"""
        pass

    @slash_command(
        name="crafty_servers",
        description="List all available Minecraft servers",
        guild_ids=[GUILD_ID]
    )
    async def list_servers(self, interaction: nextcord.Interaction):
        """List all available servers"""
        await interaction.response.defer()
        
        if not await self._check_crafty_available(interaction):
            return
        
        if not await self._refresh_servers_cache(force=True):
            await interaction.followup.send("❌ Failed to connect to Crafty Controller", ephemeral=True)
            return
        
        if not self._servers_cache:
            await interaction.followup.send("No servers found on Crafty Controller")
            return
        
        embed = nextcord.Embed(
            title="🎮 Available Minecraft Servers",
            color=0x00ff00,
            timestamp=interaction.created_at
        )
        
        for server_id, server in self._servers_cache.items():
            name = server.get("server_name", f"Server {server_id}")
            server_type = server.get("type", "unknown")
            
            embed.add_field(
                name=f"{name}",
                value=f"**ID:** {server_id}\n**Type:** {server_type}",
                inline=True
            )
        
        embed.set_footer(text="Use /crafty_status <server> to see detailed information")
        await interaction.followup.send(embed=embed)
    
    @slash_command(
        name="crafty_status",
        description="Get detailed status of a Minecraft server",
        guild_ids=[GUILD_ID]
    )
    async def server_status(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server",
            autocomplete=True,
            required=True
        )
    ):
        """Get server status and statistics"""
        await interaction.response.defer()
        
        if not await self._check_crafty_available(interaction):
            return
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        # Get server statistics
        stats = await self.crafty_api.get_server_stats(server_id)
        if not stats:
            await interaction.followup.send("❌ Failed to get server statistics", ephemeral=True)
            return
        
        embed = nextcord.Embed(
            title="📊 Server Status",
            color=0x00ff00 if stats.get("running") else 0xff0000,
            timestamp=interaction.created_at
        )
        
        # Format and add server stats
        stats_text = self.crafty_api.format_server_stats(stats)
        embed.description = stats_text
        
        # Add additional fields
        if stats.get("running"):
            server_port = stats.get('server_id', {}).get('server_port', 25565)
            server_address = self._format_server_address(server_port)
            
            embed.add_field(
                name="🌍 Server Details",
                value=f"**Address:** {server_address}",
                inline=True
            )
            
            if stats.get("version"):
                embed.add_field(
                    name="📋 Version",
                    value=stats.get("version", "Unknown"),
                    inline=True
                )
        
        await interaction.followup.send(embed=embed)
    
    @server_status.on_autocomplete("server")
    async def server_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection"""
        try:
            if not self.crafty_available:
                choices = ["Crafty Controller not available"]
            else:
                choices = await self._get_server_choices(current)
                if not choices:
                    choices = ["No servers found"]
            
            await interaction.response.send_autocomplete(choices)
        except Exception as e:
            logger.error(f"Error in autocomplete: {e}")
            try:
                await interaction.response.send_autocomplete(["Error loading servers"])
            except:
                pass  # Interaction already acknowledged
    
    @slash_command(
        name="crafty_start",
        description="Start a Minecraft server",
        guild_ids=[GUILD_ID]
    )
    async def start_server(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server to start",
            autocomplete=True,
            required=True
        )
    ):
        """Start a server"""
        await interaction.response.defer()
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        # Check current status first
        stats = await self.crafty_api.get_server_stats(server_id)
        if stats and stats.get("running"):
            await interaction.followup.send("⚠️ Server is already running!", ephemeral=True)
            return
        
        success = await self.crafty_api.start_server(server_id)
        if success:
            server_name = stats.get("server_id", {}).get("server_name", f"Server {server_id}") if stats else f"Server {server_id}"
            embed = nextcord.Embed(
                title="🚀 Server Starting",
                description=f"**{server_name}** is now starting up...\n\nIt may take a few minutes to fully start.",
                color=0x00ff00,
                timestamp=interaction.created_at
            )
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("❌ Failed to start server. Check Crafty Controller logs.", ephemeral=True)
    
    @start_server.on_autocomplete("server")
    async def start_server_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection"""
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
    
    @slash_command(
        name="crafty_stop",
        description="Stop a Minecraft server",
        guild_ids=[GUILD_ID]
    )
    async def stop_server(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server to stop",
            autocomplete=True,
            required=True
        )
    ):
        """Stop a server"""
        await interaction.response.defer()
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        # Check current status first
        stats = await self.crafty_api.get_server_stats(server_id)
        if stats and not stats.get("running"):
            await interaction.followup.send("⚠️ Server is already stopped!", ephemeral=True)
            return
        
        # Check for active players (protection)
        player_count = stats.get("online", 0) if stats else 0
        if player_count > 0:
            embed = nextcord.Embed(
                title="🛡️ Player Protection Active",
                description=f"Cannot stop server with **{player_count} active player(s)** online.\n\n"
                           f"Please wait for players to disconnect or use `/crafty_command` to warn them first.",
                color=0xff9900,
                timestamp=interaction.created_at
            )
            embed.add_field(
                name="💡 Alternative",
                value="Use `/crafty_command <server> say Server will restart in 5 minutes` to notify players.",
                inline=False
            )
            await interaction.followup.send(embed=embed)
            return
        
        success = await self.crafty_api.stop_server(server_id)
        if success:
            server_name = stats.get("server_id", {}).get("server_name", f"Server {server_id}") if stats else f"Server {server_id}"
            embed = nextcord.Embed(
                title="🛑 Server Stopping",
                description=f"**{server_name}** is now shutting down gracefully...",
                color=0xff9900,
                timestamp=interaction.created_at
            )
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("❌ Failed to stop server. Check Crafty Controller logs.", ephemeral=True)
    
    @stop_server.on_autocomplete("server")
    async def stop_server_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection"""
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
    
    @slash_command(
        name="crafty_restart",
        description="Restart a Minecraft server",
        guild_ids=[GUILD_ID]
    )
    async def restart_server(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server to restart",
            autocomplete=True,
            required=True
        )
    ):
        """Restart a server"""
        await interaction.response.defer()
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        # Check for active players before restarting
        stats = await self.crafty_api.get_server_stats(server_id)
        if stats and stats.get("online", 0) > 0:
            player_count = stats.get("online", 0)
            server_name = stats.get("server_id", {}).get("server_name", f"Server {server_id}")
            
            # Create confirmation embed and view
            embed = nextcord.Embed(
                title="⚠️ Server Has Active Players",
                description=f"**{server_name}** currently has **{player_count}** player{'s' if player_count != 1 else ''} online.\n\n"
                           f"Restarting now would disconnect them. Do you want to continue?",
                color=0xff9900,
                timestamp=interaction.created_at
            )
            embed.add_field(
                name="⏱️ Timeout",
                value="This confirmation will expire in 60 seconds.",
                inline=False
            )
            
            view = RestartConfirmationView(self.crafty_api, server_id, server_name, player_count)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return
        
        # No players online, proceed with restart immediately
        success = await self.crafty_api.restart_server(server_id)
        if success:
            stats = await self.crafty_api.get_server_stats(server_id)
            server_name = stats.get("server_id", {}).get("server_name", f"Server {server_id}") if stats else f"Server {server_id}"
            
            embed = nextcord.Embed(
                title="🔄 Server Restarting",
                description=f"**{server_name}** is now restarting...\n\nThis may take a few minutes.",
                color=0x0099ff,
                timestamp=interaction.created_at
            )
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("❌ Failed to restart server. Check Crafty Controller logs.", ephemeral=True)
    
    @restart_server.on_autocomplete("server")
    async def restart_server_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection"""
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
    
    @slash_command(
        name="crafty_backup",
        description="Create a backup of a Minecraft server",
        guild_ids=[GUILD_ID]
    )
    async def backup_server(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server to backup",
            autocomplete=True,
            required=True
        )
    ):
        """Create a server backup"""
        await interaction.response.defer()
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        success = await self.crafty_api.backup_server(server_id)
        if success:
            stats = await self.crafty_api.get_server_stats(server_id)
            server_name = stats.get("server_id", {}).get("server_name", f"Server {server_id}") if stats else f"Server {server_id}"
            
            embed = nextcord.Embed(
                title="💾 Backup Started",
                description=f"Creating backup for **{server_name}**...\n\nThis may take several minutes depending on world size.",
                color=0x9900ff,
                timestamp=interaction.created_at
            )
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("❌ Failed to start backup. Check Crafty Controller logs.", ephemeral=True)
    
    @backup_server.on_autocomplete("server")
    async def backup_server_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection"""
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
    
    @slash_command(
        name="crafty_command",
        description="Send a command to a running Minecraft server",
        guild_ids=[GUILD_ID]
    )
    async def send_command(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(
            description="Select a server",
            autocomplete=True,
            required=True
        ),
        command: str = SlashOption(
            description="Command to send (without leading slash)",
            required=True
        )
    ):
        """Send a command to the server console"""
        await interaction.response.defer()
        
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        
        # Check if server is running
        stats = await self.crafty_api.get_server_stats(server_id)
        if not stats or not stats.get("running"):
            await interaction.followup.send("❌ Server must be running to send commands!", ephemeral=True)
            return
        
        # Remove leading slash if present
        command = command.lstrip('/')
        
        success = await self.crafty_api.send_command(server_id, command)
        if success:
            server_name = stats.get("server_id", {}).get("server_name", f"Server {server_id}")
            embed = nextcord.Embed(
                title="📡 Command Sent",
                description=f"Sent command to **{server_name}**:\n`{command}`",
                color=0x00ff00,
                timestamp=interaction.created_at
            )
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("❌ Failed to send command. Check if server is running.", ephemeral=True)
    
    @send_command.on_autocomplete("server")
    async def send_command_autocomplete(self, interaction: nextcord.Interaction, current: str):
        """Autocomplete for server selection"""
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)

    # /crafty subcommands - cleaner structure without prefixes
    
    @crafty_parent.subcommand(name="servers", description="List all available Minecraft servers")
    async def crafty_servers_sub(self, interaction: nextcord.Interaction):
        """List all available servers"""
        await self.list_servers(interaction)
    
    @crafty_parent.subcommand(name="start", description="Start a Minecraft server")
    async def crafty_start_sub(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server to start", autocomplete=True, required=True)
    ):
        """Start a server"""
        await self.start_server(interaction, server)
    
    @crafty_start_sub.on_autocomplete("server")
    async def crafty_start_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
        
    @crafty_parent.subcommand(name="stop", description="Stop a Minecraft server")
    async def crafty_stop_sub(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server to stop", autocomplete=True, required=True)
    ):
        """Stop a server"""
        await self.stop_server(interaction, server)
        
    @crafty_stop_sub.on_autocomplete("server")
    async def crafty_stop_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
        
    @crafty_parent.subcommand(name="restart", description="Restart a Minecraft server")
    async def crafty_restart_sub(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server to restart", autocomplete=True, required=True)
    ):
        """Restart a server"""
        await self.restart_server(interaction, server)
        
    @crafty_restart_sub.on_autocomplete("server")  
    async def crafty_restart_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
        
    @crafty_parent.subcommand(name="status", description="Get server status and statistics")
    async def crafty_status_sub(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server to check", autocomplete=True, required=True)
    ):
        """Get server status"""
        await self.server_status(interaction, server)
        
    @crafty_status_sub.on_autocomplete("server")
    async def crafty_status_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
        
    @crafty_parent.subcommand(name="backup", description="Create a server backup")
    async def crafty_backup_sub(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server to backup", autocomplete=True, required=True)
    ):
        """Create a server backup"""
        await self.backup_server(interaction, server)
        
    @crafty_backup_sub.on_autocomplete("server")
    async def crafty_backup_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)
        
    @crafty_parent.subcommand(name="command", description="Send a command to server console (Admin only)")
    async def crafty_command_sub(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server", autocomplete=True, required=True),
        cmd: str = SlashOption(description="Command to send (without leading slash)", required=True)
    ):
        """Send a command to server console (Admin only)"""
        # Check admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
            return
        await self.send_command(interaction, server, cmd)
        
    @crafty_command_sub.on_autocomplete("server")
    async def crafty_command_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = await self._get_server_choices(current)
        await interaction.response.send_autocomplete(choices)

    # Conditional automation subcommands - only available when enabled
    def add_automation_subcommands(self):
        """Add automation subcommands if they are enabled"""
        if admin_command_manager.is_command_enabled("CraftyController", "automation_config"):
            
            @self.crafty_parent.subcommand(name="automation", description="Configure server automation settings")
            async def crafty_automation_sub(
                self,
                interaction: nextcord.Interaction,
                server: str = SlashOption(description="Select a server", autocomplete=True, required=True),
                auto_shutdown: bool = SlashOption(description="Enable auto-shutdown when no players", required=False, default=None),
                idle_timeout: int = SlashOption(description="Minutes of 0 players before shutdown (5-180, default: 10)", required=False, default=None, min_value=5, max_value=180),
                always_online: bool = SlashOption(description="Keep server online 24/7 (overrides auto-shutdown)", required=False, default=None)
            ):
                """Configure automation settings for a server"""
                await self.automation_config(interaction, server, auto_shutdown, idle_timeout, always_online)
            
            @crafty_automation_sub.on_autocomplete("server")
            async def crafty_automation_autocomplete(self, interaction: nextcord.Interaction, current: str):
                choices = await self._get_server_choices(current)
                await interaction.response.send_autocomplete(choices)
        
        if admin_command_manager.is_command_enabled("CraftyController", "automation_status"):
            
            @self.crafty_parent.subcommand(name="automation-status", description="View automation status for all servers")
            async def crafty_automation_status_sub(self, interaction: nextcord.Interaction):
                """View automation status for all servers"""
                await self.automation_status(interaction)

def setup(bot):
    bot.add_cog(CraftyController(bot))