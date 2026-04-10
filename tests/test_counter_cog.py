"""Counter cog DB logic with a temporary SQLite file."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_counter_create_update_get(tmp_path) -> None:
    from main_bot.cogs.production import counter as counter_mod

    db_file = tmp_path / "counter_test.db"
    counter_mod.DB_PATH = str(db_file)

    from main_bot.cogs.production.counter import Counter

    cog = Counter(MagicMock())
    await cog.create_tables()
    await cog.update_user_counter(999001, 7, "default")
    data = await cog.get_user_counter_data(999001)
    assert data is not None
    assert data["count"] == 7
    assert data["category"] == "default"
