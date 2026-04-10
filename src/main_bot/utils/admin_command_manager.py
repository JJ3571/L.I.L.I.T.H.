import json
import os
import logging
from pathlib import Path
from typing import Dict, Set, Optional

from nextcord.ext import commands
import nextcord

from main_bot.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

_DEFAULT_ADMIN_COMMANDS_PATH = PROJECT_ROOT / "server_configs" / "admin_commands.json"


class AdminCommandManager:
    """Manages the visibility and availability of admin commands"""

    def __init__(self, config_path: Optional[str | Path] = None):
        # Anchor to repo root so first-run creation does not depend on process cwd (uv run, systemd, etc.).
        self.config_path = str(_DEFAULT_ADMIN_COMMANDS_PATH if config_path is None else config_path)
        self.enabled_commands: Dict[str, Set[str]] = {}  # cog_name -> set of command names
        self.load_config()
    
    def load_config(self):
        """Load admin command configuration from file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    # Convert lists back to sets
                    self.enabled_commands = {
                        cog_name: set(commands) 
                        for cog_name, commands in data.items()
                    }
                logger.info(f"Loaded admin command config: {self.enabled_commands}")
            else:
                # Default configuration - start with admin commands disabled
                self.enabled_commands = {
                    "CraftyController": {
                        # Core subcommands (servers, start, stop, restart, status, backup) are always available
                        # Admin command (command) is always available but requires permissions
                        # Only automation subcommands are toggleable and start disabled
                    },
                    "ExampleAdminCog": {
                        # Regular commands would be enabled, but they use @slash_command
                        # Only admin commands using @conditional_slash_command start disabled
                    }
                }
                self.save_config()
        except Exception as e:
            logger.error(f"Error loading admin command config: {e}")
            self.enabled_commands = {}
    
    def save_config(self):
        """Save admin command configuration to file"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            # Convert sets to lists for JSON serialization
            data = {
                cog_name: list(commands) 
                for cog_name, commands in self.enabled_commands.items()
            }
            
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("Saved admin command configuration")
        except Exception as e:
            logger.error(f"Error saving admin command config: {e}")
    
    def is_command_enabled(self, cog_name: str, command_name: str) -> bool:
        """Check if a specific admin command is enabled"""
        return command_name in self.enabled_commands.get(cog_name, set())
    
    def enable_command(self, cog_name: str, command_name: str) -> bool:
        """Enable an admin command"""
        if cog_name not in self.enabled_commands:
            self.enabled_commands[cog_name] = set()
        
        if command_name not in self.enabled_commands[cog_name]:
            self.enabled_commands[cog_name].add(command_name)
            self.save_config()
            return True
        return False
    
    def disable_command(self, cog_name: str, command_name: str) -> bool:
        """Disable an admin command"""
        if cog_name in self.enabled_commands and command_name in self.enabled_commands[cog_name]:
            self.enabled_commands[cog_name].remove(command_name)
            self.save_config()
            return True
        return False
    
    def get_all_admin_commands(self, cog_name: str) -> Dict[str, bool]:
        """Get all admin commands for a cog with their enabled status"""
        # Define all available admin commands per cog
        all_commands = {
            "CraftyController": {
                "automation_config": "Configure server automation settings",
                "automation_status": "View automation settings for all servers"
            },
            "ExampleAdminCog": {
                "example_config": "Configure example cog settings",
                "example_reset": "Reset example cog data"
            }
        }
        
        if cog_name not in all_commands:
            return {}
        
        return {
            cmd: self.is_command_enabled(cog_name, cmd)
            for cmd in all_commands[cog_name].keys()
        }
    
    def get_command_description(self, cog_name: str, command_name: str) -> str:
        """Get description for a command"""
        descriptions = {
            "CraftyController": {
                "automation_config": "Configure server automation settings",
                "automation_status": "View automation settings for all servers"
            },
            "ExampleAdminCog": {
                "example_config": "Configure example cog settings",
                "example_reset": "Reset example cog data"
            }
        }
        
        return descriptions.get(cog_name, {}).get(command_name, "Admin command")

# Global instance
admin_command_manager = AdminCommandManager()