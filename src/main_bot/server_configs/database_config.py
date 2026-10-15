"""
Database configuration for Discord Bot Sandbox.

Runtime: single PostgreSQL database, multiple schemas.
"""

# Ordered list of schemas the bot creates at startup.
SCHEMA_KEYS = [
    "birthday",
    "buzzer",
    "counter",
    "coc",
    "economy",
    "event",
    "greek_gods",
    "pokemon",
    "powerups",
    "request",
    "wager",
    "waterboard",
    "tierlist",
    "trivia",
    "crafty_automation",
    "guild_config",
]
