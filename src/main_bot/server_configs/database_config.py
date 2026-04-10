"""
Database configuration for Discord Bot Sandbox
Centralized database path management. 

May seem redundant, but it's good practice and allows for 
easier maintenance and future expansion.
"""
import os

from main_bot.paths import PROJECT_ROOT

# Database directory relative to the project root
DB_DIR = os.fspath(PROJECT_ROOT / "databases")


def get_db_path(db_name: str) -> str:
    """
    Get the full path to a database file.

    Args:
        db_name: Name of the database file (e.g., "economy.db")

    Returns:
        Full path to the database file
    """
    return os.path.join(DB_DIR, db_name)


# Database paths for each cog
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
}

# Ensure database directory exists
os.makedirs(DB_DIR, exist_ok=True)
