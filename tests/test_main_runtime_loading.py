"""Runtime loading checks for main bot startup behavior."""

from __future__ import annotations

import pytest

from main_bot import main


@pytest.mark.asyncio
async def test_main_load_extensions_registers_logging_command() -> None:
    # Keep test isolated from any previous extension state.
    for ext in list(main.bot.extensions):
        main.bot.unload_extension(ext)

    await main.load_extensions("production")

    assert "logging" in main.bot.all_commands

    for ext in list(main.bot.extensions):
        main.bot.unload_extension(ext)
