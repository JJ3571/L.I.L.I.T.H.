"""Shared pytest setup: env vars must exist before importing main_bot config (import-time reads)."""

import os

# Config reads os.environ when modules load; set placeholders before any main_bot import.
_DEFAULTS = (
    ("ENVIRONMENT", "development"),
    ("DISCORD_BOT_TOKEN", "test-ci-token"),
    ("GUILD_ID", "0"),
    ("APPLICATION_ID", "0"),
)
for _key, _val in _DEFAULTS:
    os.environ.setdefault(_key, _val)
