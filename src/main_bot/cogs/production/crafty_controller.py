import nextcord
from nextcord.ext import commands, tasks
from nextcord import slash_command, SlashOption
import asyncio
import logging
import re
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import json

from main_bot.cog_log_mixin import CogLogMixin
from main_bot.server_configs.config import CRAFTY_BASE_URL, CRAFTY_USERNAME, CRAFTY_PASSWORD, GUILD_ID, IS_DEVELOPMENT
from main_bot.utils.crafty_api import CraftyAPI
from main_bot.utils.crafty_automation import CraftyAutomationDB, ServerAutomationConfig
from main_bot.utils.admin_command_manager import admin_command_manager

logger = logging.getLogger(__name__)

# Java edition: 3–16 chars, [a-zA-Z0-9_]
MINECRAFT_JAVA_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,16}$")


def _normalize_minecraft_java_username(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip()
    if not MINECRAFT_JAVA_USERNAME_RE.match(s):
        return None
    return s


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
        
        await interaction.edit_original_message(embed=embed, view=self)
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

class CraftyController(commands.Cog, CogLogMixin):
    """Discord cog for managing Minecraft servers via Crafty Controller"""
    
    def __init__(self, bot):
        self.bot = bot
        self.crafty_available = self._check_crafty_config()
        
        if self.crafty_available:
            self.crafty_api = CraftyAPI(CRAFTY_BASE_URL, CRAFTY_USERNAME, CRAFTY_PASSWORD)
            self.automation_db = CraftyAutomationDB()
            self.cog_print(f"[CRAFTY] Initialized with URL: {CRAFTY_BASE_URL}")
            
            # Start automation tasks
            asyncio.create_task(self._init_automation())
        else:
            self.crafty_api = None
            self.automation_db = None
            self.cog_print("[CRAFTY] Not available - missing configuration")
            
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
            # Only show server name in autocomplete, no ID
            if current.lower() in name.lower():
                choices.append(name)
        
        return choices[:25]  # Discord limit
    
    def _parse_server_choice(self, choice: str) -> Optional[str]:
        """Parse server ID from autocomplete choice"""
        try:
            logger.info(f"Parsing server choice: '{choice}'")
            
            # Look up server ID by name in the cache
            for server_id, server in self._servers_cache.items():
                server_name = server.get("server_name", f"Server {server_id}")
                if server_name == choice:
                    logger.info(f"Found server ID '{server_id}' for name '{choice}'")
                    return server_id
            
            # Fallback: try the old format for backwards compatibility
            if "(ID: " in choice and choice.endswith(")"):
                id_part = choice.split("(ID: ")[1][:-1]
                logger.info(f"Extracted server ID from old format: '{id_part}'")
                return id_part
            
            logger.warning(f"Could not find server ID for choice: '{choice}'")
                
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
    
    def _format_creation_date(self, created_str: str) -> str:
        """Format creation date for display"""
        try:
            from datetime import datetime
            # Parse the ISO format from the API
            created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            return created.strftime("%b %d, %Y")
        except:
            return "Unknown"
    
    def _calculate_uptime(self, started_str: str) -> str:
        """Calculate uptime from started timestamp"""
        try:
            from datetime import datetime
            # Parse the started time (format: "2022-05-25 15:44:05")
            started = datetime.strptime(started_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            uptime = now - started
            
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            if days > 0:
                return f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{minutes}m"
        except:
            return "Unknown"
    
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
        
        # Get stats for each server to show versions and status
        for server_id, server in self._servers_cache.items():
            name = server.get("server_name", f"Server {server_id}")
            
            # Get creation date from server info
            created_date = "Unknown"
            if server.get("created"):
                created_date = self._format_creation_date(server["created"])
            
            # Get server stats to show version and status
            stats = await self.crafty_api.get_server_stats(server_id)
            if stats:
                running = stats.get("running", False)
                status_icon = "🟢" if running else "🔴"
                status_text = "Online" if running else "Offline"
                
                version = stats.get("version", "Unknown")
                players = f"{stats.get('online', 0)}/{stats.get('max', 0)}"
                
                # Calculate uptime if server is running
                uptime_info = ""
                if running and stats.get("started"):
                    uptime = self._calculate_uptime(stats["started"])
                    uptime_info = f"\n**Uptime:** {uptime}"
                
                embed.add_field(
                    name=f"{status_icon} {name}",
                    value=f"**Version:** {version}\n**Players:** {players}\n**Created:** {created_date}{uptime_info}",
                    inline=True
                )
            else:
                # Fallback if stats unavailable
                server_type = server.get("type", "unknown")
                embed.add_field(
                    name=f"❓ {name}",
                    value=f"**Type:** {server_type}\n**Created:** {created_date}\n**Status:** Unknown",
                    inline=True
                )
        
        embed.set_footer(text="Use /crafty status <server> to see detailed information")
        await interaction.followup.send(embed=embed)
    
    async def server_status(
        self,
        interaction: nextcord.Interaction,
        server: str
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
                name="🌍 Connection Info",
                value=f"**Server Address:** {server_address}",
                inline=False
            )
            
            # Add player list if there are players online
            players_data = stats.get("players", [])
            if players_data and len(players_data) > 0:
                try:
                    import json
                    if isinstance(players_data, str):
                        players_list = json.loads(players_data)
                    else:
                        players_list = players_data
                    
                    if players_list:
                        player_names = [player.get("name", "Unknown") for player in players_list]
                        embed.add_field(
                            name="� Online Players",
                            value=", ".join(player_names[:10]) + ("..." if len(player_names) > 10 else ""),
                            inline=False
                        )
                except:
                    pass  # Skip if we can't parse player data
        
        await interaction.followup.send(embed=embed)
    

    
    async def start_server(
        self,
        interaction: nextcord.Interaction,
        server: str
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
    

    
    async def stop_server(
        self,
        interaction: nextcord.Interaction,
        server: str
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
    

    
    async def restart_server(
        self,
        interaction: nextcord.Interaction,
        server: str
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
    

    
    async def backup_server(
        self,
        interaction: nextcord.Interaction,
        server: str
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
    

    
    async def send_command(
        self,
        interaction: nextcord.Interaction,
        server: str,
        command: str
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

    async def _apply_whitelist_one_server(
        self, server_id: str, usernames: List[str]
    ) -> Tuple[str, str]:
        """Run whitelist on (if needed) and whitelist add for each name on one running server."""
        stats = await self.crafty_api.get_server_stats(server_id)
        default_name = self._servers_cache.get(server_id, {}).get("server_name", f"Server {server_id}")
        if stats:
            server_name = stats.get("server_id", {}).get("server_name", default_name)
        else:
            server_name = default_name
        if not stats or not stats.get("running"):
            return server_name, "⏭️ Skipped (offline)"

        parts: List[str] = []
        ready = await self.automation_db.get_server_whitelist_ready(server_id)
        if not ready:
            ok = await self.crafty_api.send_command(server_id, "whitelist on")
            if not ok:
                return server_name, "❌ `whitelist on` failed — server not marked ready"
            await self.automation_db.set_server_whitelist_ready(server_id, True)
            parts.append("`whitelist on` sent")
        if not usernames:
            suffix = " — no names in DB to add" if parts else "No names in DB to add"
            return server_name, (parts[0] + suffix) if parts else suffix

        failed = [u for u in usernames if not await self.crafty_api.send_command(server_id, f"whitelist add {u}")]
        if failed:
            parts.append(f"⚠️ add failed: {', '.join(f'`{x}`' for x in failed)}")
        else:
            parts.append(f"✅ {len(usernames)}× whitelist add")
        return server_name, " — ".join(parts)


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

    @crafty_parent.subcommand(
        name="whitelist",
        description="Shared Java whitelist names in the Crafty DB and sync to running servers",
    )
    async def crafty_whitelist_group(self, interaction: nextcord.Interaction):
        """Parent for /crafty whitelist … (use a subcommand)."""
        pass

    @crafty_whitelist_group.subcommand(
        name="add",
        description="Add a Minecraft username to the shared list (letters, digits, underscore; 3–16 chars)",
    )
    async def crafty_whitelist_add(
        self,
        interaction: nextcord.Interaction,
        username: str = SlashOption(description="Java username", required=True),
    ):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_crafty_available(interaction):
            return
        if not self.automation_db:
            await interaction.followup.send("❌ Crafty database not available.", ephemeral=True)
            return
        name = _normalize_minecraft_java_username(username)
        if not name:
            await interaction.followup.send(
                "❌ Invalid username. Use 3–16 characters: letters, digits, and underscores only.",
                ephemeral=True,
            )
            return
        if await self.automation_db.add_whitelist_username(name):
            await interaction.followup.send(f"✅ Added `{name}` to the shared whitelist list.", ephemeral=True)
        else:
            await interaction.followup.send(f"`{name}` is already on the list.", ephemeral=True)

    @crafty_whitelist_group.subcommand(name="remove", description="Remove a Minecraft username from the shared list")
    async def crafty_whitelist_remove(
        self,
        interaction: nextcord.Interaction,
        username: str = SlashOption(description="Java username", required=True),
    ):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_crafty_available(interaction):
            return
        if not self.automation_db:
            await interaction.followup.send("❌ Crafty database not available.", ephemeral=True)
            return
        name = _normalize_minecraft_java_username(username)
        if not name:
            await interaction.followup.send(
                "❌ Invalid username. Use 3–16 characters: letters, digits, and underscores only.",
                ephemeral=True,
            )
            return
        if await self.automation_db.remove_whitelist_username(name):
            await interaction.followup.send(f"✅ Removed `{name}` from the shared list.", ephemeral=True)
        else:
            await interaction.followup.send(f"`{name}` was not on the list.", ephemeral=True)

    @crafty_whitelist_group.subcommand(name="list", description="Show all Minecraft usernames on the shared whitelist list")
    async def crafty_whitelist_list(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_crafty_available(interaction):
            return
        if not self.automation_db:
            await interaction.followup.send("❌ Crafty database not available.", ephemeral=True)
            return
        names = await self.automation_db.list_whitelist_usernames()
        embed = nextcord.Embed(
            title="📋 Shared whitelist list",
            color=0x0099FF,
            timestamp=interaction.created_at,
        )
        if names:
            embed.description = "\n".join(f"• `{n}`" for n in names)
        else:
            embed.description = "_No usernames stored yet._"
        embed.set_footer(text="Use /crafty whitelist apply to push to running servers")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @crafty_whitelist_group.subcommand(
        name="apply",
        description="On each running server: whitelist on if needed, then whitelist add for every name on the list",
    )
    async def crafty_whitelist_apply(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_crafty_available(interaction):
            return
        if not self.automation_db:
            await interaction.followup.send("❌ Crafty database not available.", ephemeral=True)
            return
        if not await self._refresh_servers_cache(force=True):
            await interaction.followup.send("❌ Failed to refresh servers from Crafty.", ephemeral=True)
            return
        usernames = await self.automation_db.list_whitelist_usernames()
        server_ids = list(self._servers_cache.keys())
        tasks = [self._apply_whitelist_one_server(sid, usernames) for sid in server_ids]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        lines: List[str] = []
        for item in raw:
            if isinstance(item, BaseException):
                logger.error(
                    "whitelist apply task failed: %s",
                    item,
                    exc_info=(type(item), item, item.__traceback__),
                )
                lines.append(f"❌ Error: {item!s}")
                continue
            sname, msg = item
            lines.append(f"**{sname}** — {msg}")
        body = "\n".join(lines) if lines else "_No servers in Crafty._"
        if len(body) > 3800:
            body = body[:3797] + "…"
        embed = nextcord.Embed(
            title="🛡️ Whitelist apply",
            description=body,
            color=0x00FF99,
            timestamp=interaction.created_at,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @crafty_whitelist_group.subcommand(
        name="confirm",
        description="Mark a server as whitelist-enabled without sending console commands (e.g. you turned it on manually)",
    )
    async def crafty_whitelist_confirm(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server", autocomplete=True, required=True),
    ):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_crafty_available(interaction):
            return
        if not self.automation_db:
            await interaction.followup.send("❌ Crafty database not available.", ephemeral=True)
            return
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        await self.automation_db.set_server_whitelist_ready(server_id, True)
        await self._refresh_servers_cache()
        name = self._servers_cache.get(server_id, {}).get("server_name", f"Server {server_id}")
        await interaction.followup.send(
            f"✅ **{name}** is marked as whitelist-ready (apply will skip `whitelist on` for this server).",
            ephemeral=True,
        )

    @crafty_whitelist_group.subcommand(
        name="unconfirm",
        description="Forget whitelist-ready state for a server so the next apply sends whitelist on again",
    )
    async def crafty_whitelist_unconfirm(
        self,
        interaction: nextcord.Interaction,
        server: str = SlashOption(description="Select a server", autocomplete=True, required=True),
    ):
        await interaction.response.defer(ephemeral=True)
        if not await self._check_crafty_available(interaction):
            return
        if not self.automation_db:
            await interaction.followup.send("❌ Crafty database not available.", ephemeral=True)
            return
        server_id = self._parse_server_choice(server)
        if not server_id:
            await interaction.followup.send("❌ Invalid server selection", ephemeral=True)
            return
        had = await self.automation_db.clear_server_whitelist_ready(server_id)
        await self._refresh_servers_cache()
        name = self._servers_cache.get(server_id, {}).get("server_name", f"Server {server_id}")
        if had:
            await interaction.followup.send(
                f"✅ Cleared whitelist-ready flag for **{name}**.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"**{name}** had no whitelist-ready flag set.", ephemeral=True
            )

    @crafty_whitelist_confirm.on_autocomplete("server")
    @crafty_whitelist_unconfirm.on_autocomplete("server")
    async def crafty_whitelist_server_autocomplete(self, interaction: nextcord.Interaction, current: str):
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