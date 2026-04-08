"""Generic entrypoint; Ideally you should be using ``uv run python -m main_bot`` or ``uv run bot``."""

from main_bot.main import run

if __name__ == "__main__":
    run()
