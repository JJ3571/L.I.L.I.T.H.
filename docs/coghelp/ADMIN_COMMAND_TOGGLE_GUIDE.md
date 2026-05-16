# Admin Command Toggle System - Developer Guide

This guide explains how to integrate the admin command toggle functionality into your own cogs, allowing you to create slash commands that can be dynamically enabled/disabled without code changes.

## Overview

The admin command toggle system allows you to:
- **Hide administrative commands** by default to keep Discord clean
- **Enable commands on-demand** when configuration is needed
- **Auto-reload cogs** when commands are toggled
- **Manage multiple cogs** with their own command sets

## Quick Start

### 1. Update Admin Command Manager

First, add your cog to the admin command manager in `utils/admin_command_manager.py`:

```python
def get_all_admin_commands(self, cog_name: str) -> Dict[str, bool]:
    """Get all admin commands for a cog with their enabled status"""
    all_commands = {
        "CraftyController": {
            "crafty_servers": "List all Minecraft servers",
            # ... existing commands ...
        },
        # Add your new cog here:
        "YourCogName": {
            "your_admin_command": "Description of your admin command",
            "another_admin_command": "Another admin command description",
        }
    }
    # ... rest of method
```

```python
def get_command_description(self, cog_name: str, command_name: str) -> str:
    """Get description for a command"""
    descriptions = {
        "CraftyController": {
            # ... existing descriptions ...
        },
        # Add your cog descriptions:
        "YourCogName": {
            "your_admin_command": "Description of your admin command",
            "another_admin_command": "Another admin command description",
        }
    }
    # ... rest of method
```

### 2. Create Your Cog with Toggleable Commands

```python
import nextcord
from nextcord.ext import commands
from nextcord import slash_command, SlashOption
from utils.admin_command_manager import admin_command_manager
from server_configs.config import GUILD_ID

def conditional_slash_command(*args, **kwargs):
    """Decorator that conditionally registers slash commands based on admin settings"""
    def decorator(func):
        command_name = func.__name__
        cog_name = "YourCogName"  # Replace with your actual cog name
        
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

class YourCogName(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    # Regular command - always visible
    @slash_command(guild_ids=[GUILD_ID])
    async def regular_command(self, interaction: nextcord.Interaction):
        """This command is always visible"""
        await interaction.response.send_message("This is a regular command!")
    
    # Admin command - toggleable visibility
    @conditional_slash_command(guild_ids=[GUILD_ID])
    async def your_admin_command(
        self,
        interaction: nextcord.Interaction,
        setting: str = SlashOption(description="Configuration setting", required=True)
    ):
        """This is an admin command that can be hidden/shown"""
        await interaction.response.send_message(f"Admin command executed with setting: {setting}")
    
    # Autocomplete still works with disabled commands
    @your_admin_command.on_autocomplete("setting")
    async def setting_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = ["option1", "option2", "option3"]
        filtered = [opt for opt in choices if current.lower() in opt.lower()]
        await interaction.response.send_autocomplete(filtered[:25])

def setup(bot):
    bot.add_cog(YourCogName(bot))
```

### 3. Update Admin Toggle Choices

Add your cog to the choices in `cogs/production/admin_command_toggle.py`:

```python
cog: str = SlashOption(
    description="Cog to manage",
    choices=["CraftyController", "YourCogName"],  # Add your cog here
    required=False,
    default="CraftyController"
),
```

## Configuration Examples

### Default Command States

You can set which commands start enabled/disabled by updating the default configuration in `utils/admin_command_manager.py`:

```python
def load_config(self):
    # ... existing code ...
    else:
        # Default configuration
        self.enabled_commands = {
            "CraftyController": {
                "crafty_servers", "crafty_start", "crafty_stop", 
                # Regular commands enabled by default
            },
            "YourCogName": {
                "regular_command",  # Always-visible commands
                # Admin commands start disabled by default
            }
        }
```

## Usage Examples

Once integrated, users can manage your commands:

```bash
# List all commands for your cog
/admin_toggle list cog:YourCogName

# Enable an admin command (auto-applies changes)
/admin_toggle enable cog:YourCogName command:your_admin_command

# Disable an admin command (auto-applies changes)  
/admin_toggle disable cog:YourCogName command:your_admin_command

# Manual reload if auto-reload fails
/admin_toggle reload cog:YourCogName
```

## Advanced Features

### Custom Conditional Logic

You can create more complex conditional logic:

```python
def conditional_slash_command(*args, **kwargs):
    def decorator(func):
        command_name = func.__name__
        cog_name = "YourCogName"
        
        # Custom logic - only enable if both conditions are met
        if (admin_command_manager.is_command_enabled(cog_name, command_name) and 
            some_other_condition()):
            return slash_command(*args, **kwargs)(func)
        else:
            return DummyCommand(func)
    return decorator
```

### Per-Server Configuration

You could extend the system to have per-server command visibility:

```python
def is_command_enabled(self, cog_name: str, command_name: str, guild_id: Optional[int] = None) -> bool:
    """Check if a command is enabled, optionally per-guild"""
    # Implementation depends on your needs
```

### Command Categories

Group related admin commands:

```python
ADMIN_COMMAND_CATEGORIES = {
    "YourCogName": {
        "basic": ["command1", "command2"],
        "advanced": ["admin_command1", "admin_command2"],
        "dangerous": ["delete_everything", "reset_all"]
    }
}

# Enable/disable entire categories
def enable_category(self, cog_name: str, category: str):
    # Implementation...
```

## Best Practices

### 1. Command Naming
- Use clear, descriptive command names
- Prefix admin commands with cog name for clarity
- Group related commands with consistent naming

### 2. Default States
- **Enable** frequently-used commands by default
- **Disable** configuration/administrative commands by default
- **Enable** troubleshooting commands if your cog is complex

### 3. Error Handling
- Always handle the case where disabled commands might be called
- Provide helpful error messages
- Log command toggle events for debugging

### 4. Documentation
- Document which commands are admin-only
- Explain what each command does in descriptions
- Update your cog's README with toggle instructions

## Testing Your Implementation

```python
# Test that your cog imports correctly
python -c "import cogs.production.your_cog_name; print('✅ Cog imports successfully')"

# Test command registration
python -c "
from utils.admin_command_manager import admin_command_manager
commands = admin_command_manager.get_all_admin_commands('YourCogName')
for cmd, enabled in commands.items():
    status = '✅' if enabled else '❌'
    print(f'{status} {cmd}')
"
```

## Troubleshooting

### Commands Not Appearing After Enable
- Check that auto-reload succeeded
- Manually run `/admin_toggle reload`
- Verify command name matches exactly (case-sensitive)

### Import Errors
- Ensure `admin_command_manager` is imported correctly
- Check that your cog name is added to all required dictionaries
- Verify conditional decorator is applied correctly

### Autocomplete Issues
- Make sure autocomplete decorators come after the conditional decorator
- Check that DummyCommand handles autocomplete methods
- Test with both enabled and disabled states

This system provides a clean, maintainable way to manage command visibility across all your cogs while keeping the Discord interface uncluttered! 🚀