# Admin Command Toggle System

This system allows you to dynamically show/hide admin commands without editing code or restarting the bot.

## Overview

- **Core commands** (start, stop, restart, status, etc.) are enabled by default
- **Administrative commands** (automation, configuration) are disabled by default  
- Commands can be toggled on/off via Discord slash commands
- Changes apply immediately after reloading the cog

## Commands

### `/admin_toggle list`
Shows all available admin commands and their current status:
- ✅ = Currently enabled and visible in Discord
- ❌ = Currently disabled and hidden from Discord

### `/admin_toggle enable [command]`
Enables a specific admin command. Use autocomplete to see available commands.

### `/admin_toggle disable [command]`  
Disables a specific admin command. Use autocomplete to see available commands.

### `/admin_toggle reload`
Manually reloads a cog (rarely needed since enable/disable auto-reload).

## Usage Examples

```
# See current status of all commands
/admin_toggle list

# Enable automation commands (auto-applies changes)
/admin_toggle enable automation_config
/admin_toggle enable automation_status

# Later, disable them when not needed (auto-applies changes)
/admin_toggle disable automation_config  
/admin_toggle disable automation_status

# Manual reload only if auto-reload fails
/admin_toggle reload
```

## Default Configuration

**Always Available (New Clean Structure):**
- `/crafty servers` - List servers
- `/crafty start` - Start servers  
- `/crafty stop` - Stop servers
- `/crafty restart` - Restart servers
- `/crafty status` - Server statistics
- `/crafty backup` - Create backups
- `/crafty command` - Send console commands (Admin only)

**Toggleable Admin Commands (Disabled by default):**
- `/crafty automation` - Configure auto-shutdown settings
- `/crafty automation-status` - View automation status

## Technical Details

- Configuration stored in `src/main_bot/server_configs/admin_commands.json` (next to the `server_configs` package; older installs may have a one-time file at repo-root `server_configs/admin_commands.json` that is migrated on load)
- Uses conditional decorators to register/skip commands at load time
- Only administrators can use `/admin_toggle` commands
- Changes persist across bot restarts
- Autocomplete shows command status (✅/❌) for easy identification

## Permissions

- Only users with Administrator permissions can toggle admin commands
- All `/admin_toggle` commands are ephemeral (only visible to the user who runs them)

This system is perfect for keeping your Discord command list clean while having administrative tools available when needed!