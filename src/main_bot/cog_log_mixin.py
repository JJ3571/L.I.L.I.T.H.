"""Mixin adding ``cog_print`` routed to combined runtime log (+ optional stdout)."""

from __future__ import annotations

import logging
import os

from main_bot.boot_log import app_log_stdout_mirror_enabled


def _full_debug_terminal() -> bool:
    raw = os.environ.get("FULL_DEBUG_IN_TERMINAL", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def cog_console_line(source_name: str, message: str) -> None:
    """For module-level helpers or UI classes that are not a ``commands.Cog`` instance."""
    if "[DEBUG]" in message and not _full_debug_terminal():
        return
    text = f"[{source_name}] {message}"
    logging.getLogger("main_bot.cogs").info("%s", text)
    if app_log_stdout_mirror_enabled():
        print(text)


class CogLogMixin:
    def cog_print(self, message: str) -> None:
        cog_console_line(self.__class__.__name__, message)
