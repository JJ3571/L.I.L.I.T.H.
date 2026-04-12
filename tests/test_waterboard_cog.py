"""
Tests for ``WaterboardCog3`` (`main_bot.cogs.production.waterboard_v3`).

The cog ties together SQLite (usage, exemptions), the Economy cog, and Discord voice /
permission APIs. Tests are layered like ``test_counter_cog.py``:

- **Persistence** — real aiosqlite on a temp DB; ``DATABASE_PATHS["waterboard"]`` is
  redirected via ``monkeypatch`` so runs never touch your real ``databases/`` file.

- **Pure helpers** — ``s_print_static``, channel selection from a mocked guild, category
  show/hide, and ``move_user_with_rate_limit`` with mocked ``Member.move_to``.

- **Purchase flow** — ``_common_waterboard_purchase_flow`` with a mocked Economy cog and
  controlled ``time.time`` for cooldown math and exemptions.

- **Slash contract** — names, descriptions, async callbacks (Discord registration hygiene).

- **Slash handlers** — mocked ``Interaction`` / members / economy; ``asyncio.create_task``
  patched where the handler spawns background voice work so tests stay deterministic.

The background ``cleanup_exempt_users`` loop is not started in tests: we patch
``Loop.start`` during ``WaterboardCog3.__init__`` and invoke the underlying coroutine
via ``WaterboardCog3.cleanup_exempt_users.coro(cog)`` when we need to exercise cleanup SQL.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import nextcord
import pytest
from nextcord.application_command import SlashApplicationCommand, SlashApplicationSubcommand
from nextcord.ext import commands

import main_bot.cogs.production.waterboard_v3 as waterboard_mod
from main_bot.cogs.production.waterboard_v3 import WaterboardCog3
from main_bot.server_configs import database_config as database_config_mod


def _close_coro_fake_create_task(coro, *, name=None):  # noqa: ARG001
    """Use as ``side_effect`` for ``patch('asyncio.create_task')`` so coroutines are not left un-awaited."""
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def waterboard_db_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    path = str(tmp_path / "waterboard_test.db")
    monkeypatch.setitem(database_config_mod.DATABASE_PATHS, "waterboard", path)
    return path


@pytest.fixture
def waterboard_bot() -> MagicMock:
    bot = MagicMock(spec=commands.Bot)
    bot.wait_until_ready = AsyncMock()
    bot.get_cog = MagicMock(return_value=None)
    bot.get_channel = MagicMock(return_value=None)
    bot.get_user = MagicMock(return_value=None)
    return bot


@pytest.fixture
def waterboard_cog(waterboard_db_path: str, waterboard_bot: MagicMock) -> WaterboardCog3:
    with patch.object(WaterboardCog3.cleanup_exempt_users, "start", MagicMock()):
        return WaterboardCog3(waterboard_bot)


def _make_member(
    uid: int = 101,
    *,
    in_voice: bool = True,
    bot: bool = False,
    mention: str | None = None,
) -> MagicMock:
    m = MagicMock(spec=nextcord.Member)
    m.id = uid
    m.bot = bot
    m.name = f"user_{uid}"
    m.mention = mention or f"<@{uid}>"
    if in_voice:
        vc = MagicMock(spec=nextcord.VoiceChannel)
        vc.id = 555001
        m.voice = MagicMock()
        m.voice.channel = vc
    else:
        m.voice = None
    return m


def _make_interaction(
    *,
    user_id: int = 201,
    guild_id: int = 1,
    in_voice: bool = True,
) -> MagicMock:
    ix = MagicMock(spec=nextcord.Interaction)
    user = _make_member(user_id, in_voice=in_voice)
    ix.user = user
    guild = MagicMock(spec=nextcord.Guild)
    guild.id = guild_id
    guild.get_channel = MagicMock(return_value=None)
    ix.guild = guild
    ix.created_at = None
    ix.response = MagicMock()
    ix.response.send_message = AsyncMock()
    ix.followup = MagicMock()
    ix.followup.send = AsyncMock()
    return ix


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestWaterboardStatic:
    def test_s_print_static_ascii_safe_string(self) -> None:
        assert WaterboardCog3.s_print_static("hello") == "hello"

    def test_s_print_static_strips_non_ascii(self) -> None:
        out = WaterboardCog3.s_print_static("caf\xe9 \u2603")
        assert out.encode("ascii", errors="replace") == out.encode("ascii")

    def test_s_print_static_non_string(self) -> None:
        assert WaterboardCog3.s_print_static(42) == "42"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class TestWaterboardDatabase:
    @pytest.mark.asyncio
    async def test_create_tables_idempotent(self, waterboard_cog: WaterboardCog3) -> None:
        await waterboard_cog.create_tables()
        await waterboard_cog.create_tables()

    @pytest.mark.asyncio
    async def test_get_last_waterboarded_time_missing(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        await waterboard_cog.create_tables()
        assert await waterboard_cog.get_last_waterboarded_time(999) is None

    @pytest.mark.asyncio
    async def test_executive_pardon_inserts_exempt_row(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        await waterboard_cog.create_tables()
        now = time.time()
        with patch("time.time", return_value=now):
            await waterboard_cog.executive_pardon(77, duration_hours=2)
        async with aiosqlite.connect(waterboard_cog.db_path) as conn:
            cur = await conn.execute(
                "SELECT exempt_until FROM exempt_users WHERE user_id = ?", (77,)
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == pytest.approx(now + 7200, abs=1.0)

    @pytest.mark.asyncio
    async def test_cleanup_exempt_users_removes_expired_rows(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()

        async with aiosqlite.connect(waterboard_cog.db_path) as conn:
            await conn.execute(
                "INSERT INTO exempt_users (user_id, exempt_until) VALUES (?, ?)",
                (1, time.time() - 60),
            )
            await conn.execute(
                "INSERT INTO exempt_users (user_id, exempt_until) VALUES (?, ?)",
                (2, time.time() + 3600),
            )
            await conn.commit()

        waterboard_bot.wait_until_ready = AsyncMock()
        await WaterboardCog3.cleanup_exempt_users.coro(waterboard_cog)

        async with aiosqlite.connect(waterboard_cog.db_path) as conn:
            cur = await conn.execute("SELECT user_id FROM exempt_users ORDER BY user_id")
            rows = await cur.fetchall()
        assert rows == [(2,)]


# ---------------------------------------------------------------------------
# Guild / channel helpers
# ---------------------------------------------------------------------------


class TestWaterboardChannelHelpers:
    def test_get_waterboard_channels_sorts_by_position_and_caps(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cat = MagicMock()
        ch_high = MagicMock(spec=nextcord.VoiceChannel)
        ch_high.position = 5
        ch_low = MagicMock(spec=nextcord.VoiceChannel)
        ch_low.position = 1
        text_ch = MagicMock()
        type(text_ch).__name__ = "TextChannel"
        cat.channels = [ch_high, text_ch, ch_low]

        guild = MagicMock(spec=nextcord.Guild)
        guild.categories = [cat]

        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 9001)
        with patch("nextcord.utils.get", return_value=cat):
            out = waterboard_cog.get_waterboard_channels(guild, count=10)
        assert out == [ch_low, ch_high]

    def test_get_waterboard_channels_missing_category(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 9001)
        with patch("nextcord.utils.get", return_value=None):
            out = waterboard_cog.get_waterboard_channels(MagicMock(), count=10)
        assert out == []

    @pytest.mark.asyncio
    async def test_show_waterboard_category_success(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        category = MagicMock()
        category.set_permissions = AsyncMock(return_value=None)
        guild = MagicMock()
        guild.default_role = MagicMock()
        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 42)
        with patch("nextcord.utils.get", return_value=category):
            ok = await waterboard_cog.show_waterboard_category(guild)
        assert ok is True
        category.set_permissions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hide_waterboard_category_returns_false_on_error(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        category = MagicMock()
        category.set_permissions = AsyncMock(side_effect=RuntimeError("api"))
        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 42)
        with patch("nextcord.utils.get", return_value=category):
            ok = await waterboard_cog.hide_waterboard_category(MagicMock())
        assert ok is False


# ---------------------------------------------------------------------------
# Voice move helper
# ---------------------------------------------------------------------------


class TestWaterboardMoveUser:
    @pytest.mark.asyncio
    async def test_move_user_with_rate_limit_success(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        user = MagicMock(spec=nextcord.Member)
        user.name = "mover"
        user.move_to = AsyncMock()
        channel = MagicMock(spec=nextcord.VoiceChannel)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ok = await waterboard_cog.move_user_with_rate_limit(user, channel)
        assert ok is True
        user.move_to.assert_awaited_once_with(channel)

    @pytest.mark.asyncio
    async def test_move_user_400_returns_false(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        user = MagicMock(spec=nextcord.Member)
        user.name = "gone"
        exc = nextcord.errors.HTTPException(MagicMock(), "bad")
        exc.status = 400
        user.move_to = AsyncMock(side_effect=exc)
        channel = MagicMock(spec=nextcord.VoiceChannel)
        ok = await waterboard_cog.move_user_with_rate_limit(user, channel, max_retries=2)
        assert ok is False

    @pytest.mark.asyncio
    async def test_move_user_429_retries_then_success(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        user = MagicMock(spec=nextcord.Member)
        user.name = "ratelimited"
        exc429 = nextcord.errors.HTTPException(MagicMock(), "slow")
        exc429.status = 429
        user.move_to = AsyncMock(side_effect=[exc429, None])
        channel = MagicMock(spec=nextcord.VoiceChannel)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ok = await waterboard_cog.move_user_with_rate_limit(user, channel, max_retries=3)
        assert ok is True
        assert user.move_to.await_count == 2

    @pytest.mark.asyncio
    async def test_move_users_in_batches(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        users = [MagicMock(spec=nextcord.Member) for _ in range(3)]
        for u in users:
            u.name = "u"
        channel = MagicMock(spec=nextcord.VoiceChannel)
        with patch.object(
            waterboard_cog,
            "move_user_with_rate_limit",
            new=AsyncMock(return_value=True),
        ) as mover:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                moved = await waterboard_cog.move_users_in_batches(
                    users, channel, batch_size=2
                )
        assert moved == users
        assert mover.await_count == 3


# ---------------------------------------------------------------------------
# Purchase flow (Economy mocked)
# ---------------------------------------------------------------------------


class TestWaterboardPurchaseFlow:
    @pytest.mark.asyncio
    async def test_common_flow_exempt_user_returns_embed(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        await waterboard_cog.create_tables()
        future = time.time() + 10_000
        async with aiosqlite.connect(waterboard_cog.db_path) as conn:
            await conn.execute(
                "INSERT INTO exempt_users (user_id, exempt_until) VALUES (?, ?)",
                (30, future),
            )
            await conn.commit()

        ix = _make_interaction()
        target = _make_member(30)
        cost, next_cost, err = await waterboard_cog._common_waterboard_purchase_flow(
            ix, target
        )
        assert cost is None and next_cost is None
        assert err is not None
        assert "Exempt" in (err.title or "")

    @pytest.mark.asyncio
    async def test_common_flow_no_economy_cog(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        waterboard_bot.get_cog.return_value = None
        ix = _make_interaction()
        target = _make_member(31)
        cost, next_cost, err = await waterboard_cog._common_waterboard_purchase_flow(
            ix, target
        )
        assert err is not None and "Economy" in (err.description or "")

    @pytest.mark.asyncio
    async def test_common_flow_insufficient_balance(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=5)
        waterboard_bot.get_cog.return_value = econ
        ix = _make_interaction(user_id=55)
        target = _make_member(32)
        cost, next_cost, err = await waterboard_cog._common_waterboard_purchase_flow(
            ix, target
        )
        assert err is not None and "Insufficient" in (err.title or "")

    @pytest.mark.asyncio
    async def test_common_flow_success_first_tier(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=10_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ
        ix = _make_interaction(user_id=60)
        target = _make_member(40)
        t0 = 1_000_000.0
        with patch("time.time", return_value=t0):
            cost, next_cost, err = await waterboard_cog._common_waterboard_purchase_flow(
                ix, target
            )
        assert err is None
        assert cost == 200
        assert next_cost == 400
        econ.deduct_user_balance.assert_awaited_once_with(60, 200)

    @pytest.mark.asyncio
    async def test_common_flow_enhanced_multiplier(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=10_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ
        ix = _make_interaction(user_id=61)
        target = _make_member(41)
        with patch("time.time", return_value=2_000_000.0):
            cost, next_cost, err = await waterboard_cog._common_waterboard_purchase_flow(
                ix, target, is_enhanced=True, cost_multiplier=1.5
            )
        assert err is None
        assert cost == int(200 * 1.5)
        assert next_cost == int(200 * 1.5 * 2)

    @pytest.mark.asyncio
    async def test_common_flow_usage_resets_after_30_minutes(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=10_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ
        t_old = 3_000_000.0
        async with aiosqlite.connect(waterboard_cog.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO waterboarded_users
                (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent)
                VALUES (?, ?, ?, ?, ?)
                """,
                (42, t_old, 3, 1, 200),
            )
            await conn.commit()

        ix = _make_interaction(user_id=62)
        target = _make_member(42)
        t_new = t_old + 1801
        with patch("time.time", return_value=t_new):
            cost, next_cost, err = await waterboard_cog._common_waterboard_purchase_flow(
                ix, target
            )
        assert err is None
        assert cost == 200
        assert next_cost == 400


# ---------------------------------------------------------------------------
# Slash registration
# ---------------------------------------------------------------------------


class TestWaterboardSlashRegistration:
    def test_root_slash_commands_exist(self, waterboard_cog: WaterboardCog3) -> None:
        names = {
            cmd.name
            for _, cmd in inspect_get_slash_commands(waterboard_cog)
            if isinstance(cmd, SlashApplicationCommand)
        }
        assert names >= {
            "waterboard",
            "enhanced-waterboard",
            "waterboard-party",
            "waterboard-ranks",
            "executivepardon",
        }

    def test_waterboard_callbacks_are_async(self, waterboard_cog: WaterboardCog3) -> None:
        for _, cmd in inspect_get_slash_commands(waterboard_cog):
            assert inspect.iscoroutinefunction(cmd.callback)


def inspect_get_slash_commands(cog_instance):
    out = []
    for name, attr in inspect.getmembers(type(cog_instance)):
        if isinstance(attr, (SlashApplicationCommand, SlashApplicationSubcommand)):
            bound = getattr(cog_instance, name)
            out.append((name, bound))
    return out


# ---------------------------------------------------------------------------
# Slash handlers
# ---------------------------------------------------------------------------


class TestWaterboardSlashHandlers:
    @pytest.mark.asyncio
    async def test_executivepardon_denies_non_admin(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(waterboard_mod, "admin_user_ids", [999])
        ix = _make_interaction(user_id=100)
        target = _make_member(200)
        cmd = waterboard_cog.executivepardon_slash_command
        await cmd.callback(waterboard_cog, ix, target, duration=1)
        ix.response.send_message.assert_awaited_once()
        assert ix.response.send_message.await_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_executivepardon_admin_success(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await waterboard_cog.create_tables()
        monkeypatch.setattr(waterboard_mod, "admin_user_ids", [201])
        ix = _make_interaction(user_id=201)
        target = _make_member(888)
        cmd = waterboard_cog.executivepardon_slash_command
        await cmd.callback(waterboard_cog, ix, target, duration=3)
        ix.response.send_message.assert_awaited_once()
        kwargs = ix.response.send_message.await_args.kwargs
        assert kwargs.get("ephemeral") is False

    @pytest.mark.asyncio
    async def test_waterboard_sends_error_embed_when_not_in_voice(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=10_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ
        ix = _make_interaction()
        target = _make_member(300, in_voice=False)
        with patch("time.time", return_value=5_000_000.0):
            await waterboard_cog.waterboard.callback(waterboard_cog, ix, target)
        ix.response.send_message.assert_awaited()
        ix.followup.send.assert_awaited()
        last = ix.followup.send.await_args
        assert "not in a voice" in (last.kwargs["embed"].title or "").lower() or "cancelled" in (
            last.kwargs["embed"].title or ""
        ).lower()

    @pytest.mark.asyncio
    async def test_waterboard_spawns_task_when_configured(
        self,
        waterboard_cog: WaterboardCog3,
        waterboard_bot: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=10_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ
        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 12345)

        ix = _make_interaction()
        target = _make_member(301)
        with patch("time.time", return_value=6_000_000.0):
            with patch("asyncio.create_task") as ct:
                ct.side_effect = _close_coro_fake_create_task
                await waterboard_cog.waterboard.callback(waterboard_cog, ix, target)
        ct.assert_called_once()

    @pytest.mark.asyncio
    async def test_waterboard_config_error_when_category_unset(
        self,
        waterboard_cog: WaterboardCog3,
        waterboard_bot: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await waterboard_cog.create_tables()
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=10_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ
        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 0)

        ix = _make_interaction()
        target = _make_member(302)
        with patch("time.time", return_value=7_000_000.0):
            with patch("asyncio.create_task") as ct:
                ct.side_effect = _close_coro_fake_create_task
                await waterboard_cog.waterboard.callback(waterboard_cog, ix, target)
        ct.assert_not_called()
        assert ix.followup.send.await_count >= 1
        emb = ix.followup.send.await_args_list[-1].kwargs.get("embed")
        assert emb and "Configuration" in (emb.title or "")

    @pytest.mark.asyncio
    async def test_waterboard_party_not_in_voice(
        self, waterboard_cog: WaterboardCog3
    ) -> None:
        ix = _make_interaction(in_voice=False)
        await waterboard_cog.waterboard_party.callback(waterboard_cog, ix)
        ix.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_waterboard_party_no_targets(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=99_999)
        waterboard_bot.get_cog.return_value = econ
        ix = _make_interaction()
        vc = ix.user.voice.channel
        bot_m = _make_member(402, in_voice=True, bot=True)
        # Caller is the only non-bot human → no targets to waterboard
        vc.members = [ix.user, bot_m]
        await waterboard_cog.waterboard_party.callback(waterboard_cog, ix)
        sent = ix.response.send_message.await_args.kwargs["embed"]
        assert "No Targets" in (sent.title or "") or "no other" in (sent.description or "").lower()

    @pytest.mark.asyncio
    async def test_waterboard_party_success_deducts_and_tasks(
        self,
        waterboard_cog: WaterboardCog3,
        waterboard_bot: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await waterboard_cog.create_tables()
        monkeypatch.setattr(waterboard_mod, "waterboard_category_id", 99)
        econ = MagicMock()
        econ.get_user_balance = AsyncMock(return_value=50_000)
        econ.deduct_user_balance = AsyncMock()
        waterboard_bot.get_cog.return_value = econ

        ix = _make_interaction(user_id=500)
        vc = ix.user.voice.channel
        a = _make_member(501, in_voice=True)
        b = _make_member(502, in_voice=True)
        vc.members = [ix.user, a, b]

        with patch("asyncio.create_task") as ct:
            ct.side_effect = _close_coro_fake_create_task
            await waterboard_cog.waterboard_party.callback(waterboard_cog, ix)

        econ.deduct_user_balance.assert_awaited()
        ct.assert_called_once()
        assert ix.response.send_message.await_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_leaderboard_empty(self, waterboard_cog: WaterboardCog3) -> None:
        await waterboard_cog.create_tables()
        ix = _make_interaction()
        await waterboard_cog.leaderboard.callback(waterboard_cog, ix)
        emb = ix.response.send_message.await_args.kwargs["embed"]
        assert "No waterboard" in (emb.description or "") or "No waterboard" in (emb.title or "")

    @pytest.mark.asyncio
    async def test_leaderboard_with_rows(
        self, waterboard_cog: WaterboardCog3, waterboard_bot: MagicMock
    ) -> None:
        await waterboard_cog.create_tables()
        async with aiosqlite.connect(waterboard_cog.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO waterboarded_users
                (user_id, last_waterboarded_time, usage_count, total_waterboarded, total_coins_spent)
                VALUES (?, ?, 0, 5, 1000)
                """,
                (777, time.time()),
            )
            await conn.commit()

        u = MagicMock()
        u.name = "RankedUser"
        waterboard_bot.get_user.return_value = u
        ix = _make_interaction()
        await waterboard_cog.leaderboard.callback(waterboard_cog, ix)
        emb = ix.response.send_message.await_args.kwargs["embed"]
        assert "RankedUser" in "\n".join(
            f"{f.name}{f.value}" for f in (emb.fields or [])
        )


# ---------------------------------------------------------------------------
# Prefix: create_water_channels (permission / guild gates)
# ---------------------------------------------------------------------------


class TestWaterboardPrefixCreateChannels:
    @pytest.mark.asyncio
    async def test_create_water_channels_denies_non_admin(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(waterboard_mod, "admin_user_ids", [1])
        ctx = MagicMock()
        ctx.author.id = 2
        ctx.send = AsyncMock()
        await waterboard_cog.create_water_channels.callback(waterboard_cog, ctx, None)
        ctx.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_water_channels_wrong_guild(
        self, waterboard_cog: WaterboardCog3, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(waterboard_mod, "admin_user_ids", [9])
        monkeypatch.setattr(waterboard_mod, "GUILD_ID", 111)
        ctx = MagicMock()
        ctx.author.id = 9
        ctx.guild = MagicMock()
        ctx.guild.id = 222
        ctx.send = AsyncMock()
        await waterboard_cog.create_water_channels.callback(waterboard_cog, ctx, None)
        ctx.send.assert_awaited()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


class TestWaterboardSetup:
    @pytest.mark.asyncio
    async def test_setup_adds_cog(
        self, waterboard_db_path: str, waterboard_bot: MagicMock
    ) -> None:
        with patch.object(WaterboardCog3.cleanup_exempt_users, "start", MagicMock()):
            await waterboard_mod.setup(waterboard_bot)
        waterboard_bot.add_cog.assert_called_once()
        added = waterboard_bot.add_cog.call_args[0][0]
        assert isinstance(added, WaterboardCog3)
