"""Single-active charges for Repel Water and Executive Pardon."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from nextcord.ext import commands

from main_bot.cogs.production.shop import (
    CATEGORY_POWERUPS,
    CATEGORY_GENERAL,
    EXECUTIVE_PARDON_DURATION_HOURS,
    MAX_INVENTORY_PER_POWERUP,
    POWERUP_TYPES,
    REPEL_WATER_DURATION_SECONDS,
    REPEL_WATER_PRICE,
    REPEL_WATER_TYPE,
    SHOP_ITEMS,
    ArtRequestsButton,
    CategorySelect,
    ShopCog,
    ShopItemSelect,
    ShopPurchaseView,
    shop_catalog_embed,
    user_is_art_request_artist,
)


@pytest.fixture
def powerup_bot() -> MagicMock:
    bot = MagicMock(spec=commands.Bot)
    bot.wait_until_ready = AsyncMock()
    return bot


@pytest.fixture
def powerup_cog(powerup_bot: MagicMock, pg_pool) -> ShopCog:
    powerup_bot.pg_pool = pg_pool
    # Loop.start copies onto the instance, so patch the class method used by that copy.
    with patch("nextcord.ext.tasks.Loop.start", MagicMock()):
        return ShopCog(powerup_bot)


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


def test_clan_shop_keeps_powerups_separate_from_purchases() -> None:
    assert set(POWERUP_TYPES) == {
        "executive_pardon",
        REPEL_WATER_TYPE,
        "name_color_red",
        "name_color_blue",
    }
    for info in POWERUP_TYPES.values():
        assert info["category"] == CATEGORY_POWERUPS
        assert info["storable"] is True
    assert SHOP_ITEMS["just_one_more"]["category"] == CATEGORY_GENERAL
    assert SHOP_ITEMS["art_request"]["category"] == CATEGORY_GENERAL
    assert SHOP_ITEMS["just_one_more"]["storable"] is False
    assert SHOP_ITEMS["art_request"]["storable"] is False


@pytest.mark.asyncio
async def test_shop_purchase_view_opens_on_powerups() -> None:
    bot = MagicMock()
    with patch("nextcord.ext.tasks.Loop.start", MagicMock()):
        cog = ShopCog(bot)
    view = ShopPurchaseView(bot, 1, cog)
    category = next(child for child in view.children if isinstance(child, CategorySelect))
    items = next(child for child in view.children if isinstance(child, ShopItemSelect))
    assert [option.value for option in category.options] == [CATEGORY_POWERUPS, CATEGORY_GENERAL]
    assert [option.label for option in category.options] == ["Powerups", "General"]
    assert {option.value for option in items.options} == set(POWERUP_TYPES)
    assert items.options[0].label == "[Powerup] Executive Pardon  - 🪙 2000"
    embed = shop_catalog_embed()
    assert embed.title == "Clan Shop"
    assert [field.name for field in embed.fields] == [
        "[Powerup] Executive Pardon  - 🪙 2000",
        "[Powerup] Repel Water  - 🪙 750",
        "[Powerup] Pink @ Color  - 🪙 1000",
        "[Powerup] Blue @ Color  - 🪙 1000",
        "[General] Just One More  - 🪙 10000",
        "[General] TheGiftedNut - Art Request  - 🪙 10000",
    ]
    assert embed.fields[0].value.startswith("Grants immunity")
    assert "------" not in (embed.description or "")


@pytest.mark.asyncio
async def test_inventory_art_requests_button_is_only_for_the_artist() -> None:
    artist_id = SHOP_ITEMS["art_request"]["target_user_id"]
    other_id = SHOP_ITEMS["just_one_more"]["target_user_id"]
    assert user_is_art_request_artist(artist_id) is True
    assert user_is_art_request_artist(other_id) is False

    bot = MagicMock()
    with patch("nextcord.ext.tasks.Loop.start", MagicMock()):
        cog = ShopCog(bot)

    artist_embed, artist_view = cog.render_inventory(
        "Artist", artist_id, [], empty_text="Your inventory is empty."
    )
    _other_embed, other_view = cog.render_inventory(
        "Someone", other_id, [], empty_text="Your inventory is empty."
    )
    assert artist_view is not None
    assert any(isinstance(child, ArtRequestsButton) for child in artist_view.children)
    assert artist_embed.description == "Your inventory is empty."
    assert other_view is None
    interaction = MagicMock()
    interaction.user.display_name = "Someone"
    interaction.user.id = other_id
    interaction.response.send_message = AsyncMock()
    cog.get_user_inventory = AsyncMock(return_value=[])
    await cog.inventory_powerup.callback(cog, interaction)
    sent = interaction.response.send_message.await_args.kwargs
    assert "view" not in sent
    assert sent["embed"].description == "Your inventory is empty."
    assert sent["ephemeral"] is True
    subcommand_names = {child.name for child in ShopCog.shop_group.children.values()}
    assert "art-requests" not in subcommand_names
    assert "inventory" in subcommand_names


@pytest.mark.usefixtures("_clean_repel_rows")
class TestSingleActivePowerups:
    @pytest.mark.asyncio
    async def test_repel_second_charge_does_not_extend_the_timer(
        self, powerup_cog: ShopCog
    ) -> None:
        user_id = 4242
        now = 1_700_000_000
        with patch("main_bot.cogs.production.shop.time.time", return_value=now):
            first = await powerup_cog.activate_powerup(user_id, REPEL_WATER_TYPE, 0)
            second = await powerup_cog.activate_powerup(user_id, REPEL_WATER_TYPE, 0)
            end_time = await powerup_cog.get_powerup_end_time(user_id, REPEL_WATER_TYPE)
            assert await powerup_cog.is_repel_active(user_id) is True
        assert first is True
        assert second is False
        assert end_time == now + REPEL_WATER_DURATION_SECONDS

    @pytest.mark.asyncio
    async def test_an_expired_repel_can_be_activated_again(self, powerup_cog: ShopCog) -> None:
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
        with patch("main_bot.cogs.production.shop.time.time", return_value=now):
            started = await powerup_cog.activate_powerup(user_id, REPEL_WATER_TYPE, 0)
            end_time = await powerup_cog.get_powerup_end_time(user_id, REPEL_WATER_TYPE)
            assert await powerup_cog.is_repel_active(user_id) is True
        assert started is True
        assert end_time == now + REPEL_WATER_DURATION_SECONDS

    @pytest.mark.asyncio
    async def test_pardon_second_charge_is_refused_while_one_is_active(
        self, powerup_cog: ShopCog
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
        with patch("main_bot.cogs.production.shop.time.time", return_value=now):
            first = await powerup_cog.activate_powerup(user_id, "executive_pardon", 1)
            second = await powerup_cog.activate_powerup(user_id, "executive_pardon", 1)
            end_time = await powerup_cog.get_powerup_end_time(user_id, "executive_pardon")
        assert first is True
        assert second is False
        assert called == [1]
        assert end_time == now + EXECUTIVE_PARDON_DURATION_HOURS * 3600


@pytest.mark.asyncio
async def test_pardon_and_repel_each_hold_a_full_stack(powerup_cog: ShopCog, pg_pool) -> None:
    user_id = 9_001_016
    try:
        for _ in range(MAX_INVENTORY_PER_POWERUP):
            await powerup_cog.add_powerup_to_inventory(user_id, "executive_pardon")
            await powerup_cog.add_powerup_to_inventory(user_id, REPEL_WATER_TYPE)
        inventory = dict(await powerup_cog.get_user_inventory(user_id))
        assert inventory["executive_pardon"] == MAX_INVENTORY_PER_POWERUP
        assert inventory[REPEL_WATER_TYPE] == MAX_INVENTORY_PER_POWERUP
        assert await powerup_cog.get_user_powerup_count(user_id, "executive_pardon") == MAX_INVENTORY_PER_POWERUP
        assert await powerup_cog.get_user_powerup_count(user_id, REPEL_WATER_TYPE) == MAX_INVENTORY_PER_POWERUP
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                'DELETE FROM "powerups".powerup_inventory WHERE user_id = $1',
                user_id,
            )
