"""
Database configuration for Discord Bot Sandbox.

Runtime: single PostgreSQL database (Neon or self-hosted), multiple schemas.
Legacy: DATABASE_PATHS kept for one-time migration scripts reading old SQLite files.
"""
import os

from main_bot.paths import PROJECT_ROOT

# Database directory relative to the project root (legacy SQLite files)
DB_DIR = os.fspath(PROJECT_ROOT / "databases")


def get_db_path(db_name: str) -> str:
    """Full path to a legacy SQLite file (migration scripts only)."""
    return os.path.join(DB_DIR, db_name)


# Legacy SQLite paths — used by scripts/migrate_sqlite_to_postgres_once.py
DATABASE_PATHS = {
    "birthday": get_db_path("birthday.db"),
    "buzzer": get_db_path("buzzer.db"),
    "counter": get_db_path("counter.db"),
    "coc": get_db_path("coc.db"),
    "economy": get_db_path("economy.db"),
    "event": get_db_path("event.db"),
    "greek_gods": get_db_path("greek_gods.db"),
    "pokemon": get_db_path("pokemon.db"),
    "powerups": get_db_path("powerups.db"),
    "reminders": get_db_path("reminders.db"),
    "request": get_db_path("request.db"),
    "wager": get_db_path("wager.db"),
    "waterboard": get_db_path("waterboard.db"),
    "music": get_db_path("music.db"),
    "tierlist": get_db_path("tierlist.db"),
    "trivia": get_db_path("trivia.db"),
}

# Extra SQLite files not in DATABASE_PATHS keys (same folder)
CRAFTY_AUTOMATION_SQLITE_PATH = get_db_path("crafty_automation.db")

# PostgreSQL schema name per logical key (identical to dict keys; plus crafty_automation)
DATABASE_SCHEMAS = {k: k for k in DATABASE_PATHS}
DATABASE_SCHEMAS["crafty_automation"] = "crafty_automation"

# Ordered list of schemas the bot creates (excludes unused empty keys if any)
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
]

os.makedirs(DB_DIR, exist_ok=True)
