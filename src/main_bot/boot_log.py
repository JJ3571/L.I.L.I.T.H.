"""Stdout mirror + structured logging for boot lines (see ``main_bot.main``)."""

from __future__ import annotations

import logging
import os

BOT_STARTING = "[BOT_STARTING]"


def app_log_stdout_mirror_enabled() -> bool:
    """When true (default), ``boot_print`` and ``cog_print`` still echo lines to stdout / ``docker compose logs``."""
    raw = os.environ.get("APP_LOG_STDOUT_MIRROR", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return True


def boot_print(message: str) -> None:
    """Log startup lines to ``main_bot.boot`` (same combined file as Nextcord); optionally mirror stdout."""
    logging.getLogger("main_bot.boot").info("%s", message)
    if app_log_stdout_mirror_enabled():
        print(f"{BOT_STARTING} {message}")
