"""Single-active charges for Repel Water and Executive Pardon."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from nextcord.ext import commands

from main_bot.cogs.production.powerups import (
    EXECUTIVE_PARDON_DURATION_HOURS,
    POWERUP_TYPES,
    REPEL_WATER_DURATION_SECONDS,
    REPEL_WATER_PRICE,
    REPEL_WATER_TYPE,
    PowerupCog,
)


@pytest.fixture
def powerup_bot() -> MagicMock:
    bot = MagicMock(spec=commands.Bot)
    bot.wait_until_ready = AsyncMock()
    return bot


@pytest.fixture
def powerup_cog(powerup_bot: MagicMock, pg_pool) -> PowerupCog:
    powerup_bot.pg_pool = pg_pool
    # Loop.start copies onto the instance, so patch the class method used by that copy.
    with patch("nextcord.ext.tasks.Loop.start", MagicMock()):
        return PowerupCog(powerup_bot)


@pytest_asyncio.fixture
async def _clean_repel_rows(pg_pool):
    async def _wipe() -> None:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                '''
                DELETE FROM "powerups".active_powerups
                WHERE powerup_type = ANY($1::text[])
                ''',
                [REPEL_WATER_TYPE, "executive_pardon"],
            )

    await _wipe()
    yield
    await _wipe()


def test_repel_and_pardon_shop_copy() -> None:
    repel = POWERUP_TYPES[REPEL_WATER_TYPE]
    pardon = POWERUP_TYPES["executive_pardon"]
    assert len(repel["description"]) <= 100
    assert len(pardon["description"]) <= 100
    assert repel["price"] == REPEL_WATER_PRICE
    assert repel["storable"] is True
    assert repel["single_active"] is True
    assert repel["duration_seconds"] == 15 * 60
    assert pardon["storable"] is True
    assert pardon["single_active"] is True
    assert pardon["duration_hours"] == EXECUTIVE_PARDON_DURATION_HOURS == 1


@pytest.mark.usefixtures("_clean_repel_rows")
class TestSingleActivePowerups:
    @pytest.mark.asyncio
    async def test_repel_second_charge_does_not_extend_the_timer(
        self, powerup_cog: PowerupCog
    ) -> None:
        user_id = 4242
        now = 1_700_000_000
        with patch("main_bot.cogs.production.powerups.time.time", return_value=now):
            first = await powerup_cog.activate_powerup(user_id, REPEL_WATER_TYPE, 0)
            second = await powerup_cog.activate_powerup(user_id, REPEL_WATER_TYPE, 0)
            end_time = await powerup_cog.get_powerup_end_time(user_id, REPEL_WATER_TYPE)
            assert await powerup_cog.is_repel_active(user_id) is True
        assert first is True
        assert second is False
        assert end_time == now + REPEL_WATER_DURATION_SECONDS

    @pytest.mark.asyncio
    async def test_an_expired_repel_can_be_activated_again(self, powerup_cog: PowerupCog) -> None:
        user_id = 4244
        now = 1_900_000_000
        async with powerup_cog.bot.pg_pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO "powerups".active_powerups (user_id, powerup_type, start_time, end_time)
                VALUES ($1, $2, $3, $4)
                ''',
                user_id,
                REPEL_WATER_TYPE,
                now - 1000,
                now - 10,
            )
        with patch("main_bot.cogs.production.powerups.time.time", return_value=now):
            started = await powerup_cog.activate_powerup(user_id, REPEL_WATER_TYPE, 0)
            end_time = await powerup_cog.get_powerup_end_time(user_id, REPEL_WATER_TYPE)
            assert await powerup_cog.is_repel_active(user_id) is True
        assert started is True
        assert end_time == now + REPEL_WATER_DURATION_SECONDS

    @pytest.mark.asyncio
    async def test_pardon_second_charge_is_refused_while_one_is_active(
        self, powerup_cog: PowerupCog
    ) -> None:
        user_id = 4245
        now = 1_700_000_000
        called: list[int] = []

        class _Waterboard:
            async def executive_pardon(self, user_id: int, duration_hours: int) -> None:
                called.append(duration_hours)

            async def get_active_exemption(self, user_id: int):
                return None

            async def clear_executive_pardon(self, user_id: int) -> None:
                return None

        powerup_cog.bot.get_cog.side_effect = lambda name: _Waterboard() if name == "WaterboardCog3" else None
        with patch("main_bot.cogs.production.powerups.time.time", return_value=now):
            first = await powerup_cog.activate_powerup(user_id, "executive_pardon", 1)
            second = await powerup_cog.activate_powerup(user_id, "executive_pardon", 1)
            end_time = await powerup_cog.get_powerup_end_time(user_id, "executive_pardon")
        assert first is True
        assert second is False
        assert called == [1]
        assert end_time == now + EXECUTIVE_PARDON_DURATION_HOURS * 3600
