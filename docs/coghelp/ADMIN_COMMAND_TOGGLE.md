# Admin command toggle — operator guide

This system shows or hides selected admin commands without a code edit. Changes apply after the cog reloads.

## Overview

- Core Crafty commands stay available by default.
- Toggleable admin commands start disabled.
- Discord administrators control visibility with `/admin_toggle`.
- Settings persist in `src/main_bot/server_configs/admin_commands.json`.

## Commands

### `/admin_toggle list`

Show every toggleable admin command and its status.

- Enabled commands appear in Discord.
- Disabled commands stay hidden.

### `/admin_toggle enable [command]`

Enable one admin command. Use autocomplete to pick the command key.

### `/admin_toggle disable [command]`

Disable one admin command.

### `/admin_toggle reload`

Reload the cog manually. Enable and disable already reload in most cases.

## Usage examples

```text
/admin_toggle list
/admin_toggle enable automation_config
/admin_toggle enable automation_status
/admin_toggle disable automation_config
/admin_toggle disable automation_status
/admin_toggle reload
```

Toggle keys match Python method names (`automation_config`, `automation_status`). Discord may expose them as `/crafty_automation`, `/crafty_automation_status`, or as `/crafty` subcommands when registered.

## Default Crafty configuration

Always available:

- `/crafty servers`
- `/crafty start`
- `/crafty stop`
- `/crafty restart`
- `/crafty status`
- `/crafty backup`
- `/crafty command` (admin only)

Toggleable (disabled by default):

- Automation config (`automation_config`)
- Automation status (`automation_status`)

## Permissions

Only users with the Discord Administrator permission can run `/admin_toggle`. Responses are ephemeral.

## Developer guide

To add toggleable commands to a new cog, see [ADMIN_COMMAND_TOGGLE_GUIDE.md](ADMIN_COMMAND_TOGGLE_GUIDE.md).
