# Admin command toggle — developer guide

This guide shows how to add toggleable admin commands to a cog. Operator usage is in [ADMIN_COMMAND_TOGGLE.md](ADMIN_COMMAND_TOGGLE.md). An example lives in [example_admin_cog.py](example_admin_cog.py).

## Overview

The toggle system can:

- Hide administrative commands by default
- Enable commands on demand
- Reload cogs when commands change
- Manage multiple cogs with separate command sets

## Quick start

### 1. Register commands in the manager

Edit `src/main_bot/utils/admin_command_manager.py`. Add your cog to `get_all_admin_commands` and `get_command_description`.

```python
def get_all_admin_commands(self, cog_name: str) -> Dict[str, bool]:
    all_commands = {
        "CraftyController": {
            "automation_config": "Configure server automation settings",
            "automation_status": "View automation settings for all servers",
        },
        "YourCogName": {
            "your_admin_command": "Description of your admin command",
            "another_admin_command": "Another admin command description",
        },
    }
    # ... rest of method
```

Keys must match the Python method names on the cog.

### 2. Create the cog with conditional registration

```python
import nextcord
from nextcord.ext import commands
from nextcord import slash_command, SlashOption

from main_bot.utils.admin_command_manager import admin_command_manager
from main_bot.server_configs.config import GUILD_ID


def conditional_slash_command(*args, **kwargs):
    def decorator(func):
        command_name = func.__name__
        cog_name = "YourCogName"

        if admin_command_manager.is_command_enabled(cog_name, command_name):
            return slash_command(*args, **kwargs)(func)

        class DummyCommand:
            def __init__(self, func):
                self.func = func
                self._disabled_admin_command = True

            def on_autocomplete(self, param_name):
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

    @slash_command(guild_ids=[GUILD_ID])
    async def regular_command(self, interaction: nextcord.Interaction):
        await interaction.response.send_message("This command is always visible.")

    @conditional_slash_command(guild_ids=[GUILD_ID])
    async def your_admin_command(
        self,
        interaction: nextcord.Interaction,
        setting: str = SlashOption(description="Configuration setting", required=True),
    ):
        await interaction.response.send_message(f"Admin command with setting: {setting}")

    @your_admin_command.on_autocomplete("setting")
    async def setting_autocomplete(self, interaction: nextcord.Interaction, current: str):
        choices = ["option1", "option2", "option3"]
        filtered = [opt for opt in choices if current.lower() in opt.lower()]
        await interaction.response.send_autocomplete(filtered[:25])


def setup(bot):
    bot.add_cog(YourCogName(bot))
```

### 3. Add the cog to `/admin_toggle` choices

Edit `src/main_bot/cogs/production/admin_command_toggle.py`. Add your cog name to the `choices` list for the cog option.

```python
cog: str = SlashOption(
    description="Cog to manage",
    choices=["CraftyController", "YourCogName"],
    required=False,
    default="CraftyController",
)
```

## Default enabled set

Toggleable admin commands start disabled when `admin_commands.json` is first created. Always-visible commands use `@slash_command` and do not need an entry in the enabled set.

Config path: `src/main_bot/server_configs/admin_commands.json`.

## Operator commands after integration

```text
/admin_toggle list cog:YourCogName
/admin_toggle enable cog:YourCogName command:your_admin_command
/admin_toggle disable cog:YourCogName command:your_admin_command
/admin_toggle reload cog:YourCogName
```

## Best practices

1. Use clear method names. Toggle keys are those method names.
2. Disable configuration commands by default.
3. Keep always-visible commands on `@slash_command`.
4. Document which commands are toggleable in the cog help text.

## Testing

```bash
uv run python -c "import main_bot.cogs.production.your_cog_name; print('import ok')"

uv run python -c "
from main_bot.utils.admin_command_manager import admin_command_manager
commands = admin_command_manager.get_all_admin_commands('YourCogName')
for cmd, enabled in commands.items():
    print(cmd, enabled)
"
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Command missing after enable | Run `/admin_toggle reload`. Confirm the method name matches the toggle key. |
| Import errors | Import `main_bot.utils.admin_command_manager`. Confirm the cog name in every dictionary. |
| Autocomplete broken | Place autocomplete decorators after the conditional decorator. Confirm `DummyCommand` keeps `on_autocomplete`. |
