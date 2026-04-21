"""
Tests for the production Counter cog (`main_bot.cogs.production.counter`).

These tests follow a layered strategy common in Discord bot codebases:

1. **Data / persistence** — PostgreSQL schema ``counter`` via ``DATABASE_URL`` (see
   ``tests/conftest.py``): constraints, upserts, JSON columns.

2. **Presentation** — Embed builders are pure given a mocked ``Interaction``; they must
   not assume live Discord state beyond ``interaction.user``.

3. **Slash command contract** — Inspect ``SlashApplicationCommand`` metadata (names,
   descriptions, option required/default/max_length). This catches mistakes that would
   surface as bad command definitions or client validation errors when syncing to Discord.

4. **Slash command handlers** — Call the underlying async callbacks with ``AsyncMock``
   for ``defer``, ``followup.send``, etc. This exercises the happy path and error
   branches without the gateway. It does **not** replace an integration test against
   Discord's API, but it ensures your handler coroutines run to completion and call the
   right response APIs.

5. **UI views** — ``interaction_check``, button callbacks, and ``on_timeout`` with
   mocked messages/responses. Buttons still rely on nextcord's view machinery; we verify
   authorization logic and DB side effects.

"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import nextcord
import pytest
import pytest_asyncio

import main_bot.cogs.production.counter as counter_mod
from main_bot.cogs.production.counter import (
    Counter,
    CounterNotFoundError,
    CounterView,
    MultiCounterView,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _clean_counter_tables(pg_pool) -> None:
    async with pg_pool.acquire() as conn:
        await conn.execute('DELETE FROM "counter".counters')
        await conn.execute('DELETE FROM "counter".multi_counters')


@pytest.fixture
def counter_cog(pg_pool) -> Counter:
    bot = MagicMock()
    bot.pg_pool = pg_pool
    return Counter(bot)


def _make_interaction(
    *,
    user_id: int = 99_001,
    display_name: str = "Test User",
    avatar_url: str = "https://cdn.discordapp.com/embed/avatars/0.png",
    data: dict | None = None,
) -> MagicMock:
    """Build a minimal Interaction double for handler and view tests."""
    interaction = MagicMock()
    user = MagicMock()
    user.id = user_id
    user.display_name = display_name
    avatar = MagicMock()
    avatar.url = avatar_url
    user.display_avatar = avatar
    interaction.user = user
    interaction.data = data or {}

    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()

    sent_message = MagicMock()
    sent_message.id = 10_010
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value=sent_message)
    interaction.followup.edit_message = AsyncMock()
    return interaction


def _embed_field_names(embed) -> list[str]:
    return [f.name for f in (embed.fields or [])]


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------


class TestCounterDatabase:
    """Persistence and domain helpers (no Discord I/O)."""

    @pytest.mark.asyncio
    async def test_create_tables_idempotent(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        await counter_cog.create_tables()

    @pytest.mark.asyncio
    async def test_update_insert_and_upsert(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_user_counter(1, 3, "alpha")
        row = await counter_cog.get_user_counter_data(1)
        assert row is not None
        assert row["count"] == 3
        assert row["category"] == "alpha"
        assert isinstance(row["last_updated"], datetime.datetime)

        await counter_cog.update_user_counter(1, 10, "beta")
        row2 = await counter_cog.get_user_counter_data(1)
        assert row2["count"] == 10
        assert row2["category"] == "beta"

    @pytest.mark.asyncio
    async def test_get_user_counter_missing_returns_none(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        assert await counter_cog.get_user_counter_data(999) is None

    @pytest.mark.asyncio
    async def test_delete_user_counter_raises_when_missing(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        with pytest.raises(CounterNotFoundError):
            await counter_cog.delete_user_counter(404)

    @pytest.mark.asyncio
    async def test_delete_user_counter_removes_row(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_user_counter(2, 1, "default")
        await counter_cog.delete_user_counter(2)
        assert await counter_cog.get_user_counter_data(2) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "labels,counts",
        [
            (["A", "B"], [0, 0]),
            (["Win", "Loss", "Draw"], [1, 2, 3]),
        ],
    )
    async def test_multi_counter_roundtrip(
        self, counter_cog: Counter, labels: list[str], counts: list[int]
    ) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_multi_counter(5, "stats", labels, counts)
        data = await counter_cog.get_multi_counter_data(5, "stats")
        assert data is not None
        assert data["labels"] == labels
        assert data["counts"] == counts
        assert isinstance(data["last_updated"], datetime.datetime)

    @pytest.mark.asyncio
    async def test_delete_multi_counter_raises_when_missing(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        with pytest.raises(CounterNotFoundError):
            await counter_cog.delete_multi_counter(9, "nope")

    @pytest.mark.asyncio
    async def test_delete_multi_counter_removes_row(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_multi_counter(8, "x", ["a", "b"], [0, 0])
        await counter_cog.delete_multi_counter(8, "x")
        assert await counter_cog.get_multi_counter_data(8, "x") is None


# ---------------------------------------------------------------------------
# Embeds (presentation)
# ---------------------------------------------------------------------------


class TestCounterEmbeds:
    def test_create_embed_contains_count_and_category(self, counter_cog: Counter) -> None:
        ix = _make_interaction()
        embed = counter_cog._create_embed(ix, 42, "quests")
        assert "42" in embed.title
        assert "quests" in (embed.description or "")

    def test_create_multi_embed_fields_match_labels(self, counter_cog: Counter) -> None:
        ix = _make_interaction()
        labels = ["Foo", "Bar", "Baz"]
        counts = [1, 2, 3]
        embed = counter_cog._create_multi_embed(ix, "my_counter", labels, counts)
        names = _embed_field_names(embed)
        assert names == labels
        for f, c in zip(embed.fields, counts, strict=True):
            assert str(c) in f.value


# ---------------------------------------------------------------------------
# Slash command registration (Discord-facing contract)
# ---------------------------------------------------------------------------


class TestCounterSlashRegistration:
    """
    Static checks on ``SlashApplicationCommand`` objects.

    Discord validates option types, required flags, string lengths, and subcommand
    names when commands are synced; keeping these assertions in CI reduces the chance
    of shipping a command tree that fails registration or behaves unexpectedly in the client.
    """

    def test_counter_slash_name_and_description(self, counter_cog: Counter) -> None:
        cmd = counter_cog.counter_command
        assert cmd.name == "counter"
        assert "counter" in (cmd.description or "").lower()

    def test_counter_category_option_optional_with_default(self, counter_cog: Counter) -> None:
        opt = counter_cog.counter_command.options["category"]
        assert opt.required is False
        assert opt.default == "default"

    def test_multicounter_slash_options_required_and_lengths(self, counter_cog: Counter) -> None:
        cmd = counter_cog.multicounter_command
        assert cmd.name == "multicounter"
        assert cmd.options["name"].required is True
        assert cmd.options["name"].max_length == 32
        for key in ("option1", "option2"):
            assert cmd.options[key].required is True
            assert cmd.options[key].max_length == 20
        for key in ("option3", "option4", "option5"):
            assert cmd.options[key].required is False
            assert cmd.options[key].max_length == 20


# ---------------------------------------------------------------------------
# Slash command handlers (async, mocked Interaction)
# ---------------------------------------------------------------------------


class TestCounterSlashHandlers:
    @pytest.mark.asyncio
    async def test_counter_command_creates_row_and_sends_followup(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        ix = _make_interaction(user_id=77_001)
        await counter_cog.counter_command.callback(counter_cog, ix, category="pvp")

        ix.response.defer.assert_awaited_once()
        ix.followup.send.assert_awaited_once()
        kwargs = ix.followup.send.await_args.kwargs
        assert "embed" in kwargs and "view" in kwargs
        assert kwargs["view"].owner_id == 77_001

        stored = await counter_cog.get_user_counter_data(77_001)
        assert stored is not None
        assert stored["count"] == 0
        assert stored["category"] == "pvp"

    @pytest.mark.asyncio
    async def test_counter_command_existing_user_keeps_stored_category(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_user_counter(77_002, 5, "legacy")
        ix = _make_interaction(user_id=77_002)
        await counter_cog.counter_command.callback(counter_cog, ix, category="ignored")

        ix.followup.send.assert_awaited_once()
        embed = ix.followup.send.await_args.kwargs["embed"]
        assert "legacy" in (embed.description or "")

    @pytest.mark.asyncio
    async def test_counter_command_sends_ephemeral_on_unexpected_error(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        ix = _make_interaction()

        with patch.object(
            Counter,
            "get_user_counter_data",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await counter_cog.counter_command.callback(counter_cog, ix, category="x")

        ix.followup.send.assert_awaited()
        assert ix.followup.send.await_args.kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_multicounter_command_creates_multi_row_and_sends_followup(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        ix = _make_interaction(user_id=88_001)
        await counter_cog.multicounter_command.callback(
            counter_cog,
            ix,
            name="duel",
            option1="W",
            option2="L",
            option3=None,
            option4=None,
            option5=None,
        )

        ix.response.defer.assert_awaited_once()
        ix.followup.send.assert_awaited_once()
        data = await counter_cog.get_multi_counter_data(88_001, "duel")
        assert data["labels"] == ["W", "L"]
        assert data["counts"] == [0, 0]

    @pytest.mark.asyncio
    async def test_multicounter_command_reuses_existing_labels(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_multi_counter(88_002, "scores", ["Old", "New"], [3, 4])
        ix = _make_interaction(user_id=88_002)
        await counter_cog.multicounter_command.callback(
            counter_cog,
            ix,
            name="scores",
            option1="Should",
            option2="Ignore",
            option3=None,
            option4=None,
            option5=None,
        )
        embed = ix.followup.send.await_args.kwargs["embed"]
        assert _embed_field_names(embed) == ["Old", "New"]


# ---------------------------------------------------------------------------
# Views: authorization and button behavior
# ---------------------------------------------------------------------------


class TestCounterView:
    @pytest.mark.asyncio
    async def test_interaction_check_owner_allowed(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        view = CounterView(owner_id=10, counter_cog=counter_cog)
        ix = _make_interaction(user_id=10, data={"custom_id": "increment_counter"})
        assert await view.interaction_check(ix) is True

    @pytest.mark.asyncio
    async def test_interaction_check_non_owner_denied(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        view = CounterView(owner_id=10, counter_cog=counter_cog)
        ix = _make_interaction(user_id=11, data={"custom_id": "increment_counter"})
        assert await view.interaction_check(ix) is False
        ix.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_interaction_check_allow_others_increment_only(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        view = CounterView(owner_id=10, counter_cog=counter_cog)
        view.allow_others = True
        ix = _make_interaction(user_id=11, data={"custom_id": "increment_counter"})
        assert await view.interaction_check(ix) is True

    @pytest.mark.asyncio
    async def test_increment_button_updates_db_and_edits_message(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_user_counter(20, 4, "default")
        view = CounterView(owner_id=20, counter_cog=counter_cog)
        embed = nextcord.Embed(title="Count: **4**")
        msg = MagicMock()
        msg.id = 555
        msg.embeds = [embed]
        view.message = msg

        ix = _make_interaction(user_id=20)
        # nextcord binds view + Button into a partial; the public callback is (interaction,) only.
        await view.increment_button.callback(ix)

        row = await counter_cog.get_user_counter_data(20)
        assert row["count"] == 5
        ix.followup.edit_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_on_timeout_deletes_counter_and_edits_message(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_user_counter(30, 1, "default")
        view = CounterView(owner_id=30, counter_cog=counter_cog)
        embed = nextcord.Embed(title="Count: **1**", description="x")
        msg = MagicMock()
        msg.embeds = [embed]
        msg.edit = AsyncMock()
        view.message = msg

        await view.on_timeout()

        assert await counter_cog.get_user_counter_data(30) is None
        msg.edit.assert_awaited()


class TestMultiCounterView:
    @pytest.mark.asyncio
    async def test_interaction_check_allow_others_only_counter_prefix(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        view = MultiCounterView(
            owner_id=40,
            counter_name="m",
            labels=["a", "b"],
            counter_cog=counter_cog,
        )
        view.allow_others = True
        ix = _make_interaction(user_id=41, data={"custom_id": "settings"})
        assert await view.interaction_check(ix) is False

    @pytest.mark.asyncio
    async def test_counter_option_increments_index(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_multi_counter(50, "t", ["a", "b"], [0, 0])
        view = MultiCounterView(
            owner_id=50,
            counter_name="t",
            labels=["a", "b"],
            counter_cog=counter_cog,
        )
        msg = MagicMock()
        msg.id = 777
        view.message = msg
        ix = _make_interaction(user_id=50)

        cb = view._create_counter_callback(1)
        await cb(ix)

        data = await counter_cog.get_multi_counter_data(50, "t")
        assert data["counts"] == [0, 1]
        ix.followup.edit_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_decrement_mode_does_not_go_below_zero(
        self, counter_cog: Counter
    ) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_multi_counter(51, "t", ["a", "b"], [0, 0])
        view = MultiCounterView(
            owner_id=51,
            counter_name="t",
            labels=["a", "b"],
            counter_cog=counter_cog,
        )
        view.decrement_mode = True
        msg = MagicMock()
        msg.id = 778
        view.message = msg
        ix = _make_interaction(user_id=51)

        cb = view._create_counter_callback(0)
        await cb(ix)

        data = await counter_cog.get_multi_counter_data(51, "t")
        assert data["counts"] == [0, 0]

    @pytest.mark.asyncio
    async def test_on_timeout_deletes_multi_counter(self, counter_cog: Counter) -> None:
        await counter_cog.create_tables()
        await counter_cog.update_multi_counter(60, "x", ["a", "b"], [0, 0])
        view = MultiCounterView(
            owner_id=60,
            counter_name="x",
            labels=["a", "b"],
            counter_cog=counter_cog,
        )
        embed = nextcord.Embed(title="t")
        msg = MagicMock()
        msg.embeds = [embed]
        msg.edit = AsyncMock()
        view.message = msg

        await view.on_timeout()

        assert await counter_cog.get_multi_counter_data(60, "x") is None


# ---------------------------------------------------------------------------
# Cog setup
# ---------------------------------------------------------------------------


class TestCounterSetup:
    @pytest.mark.asyncio
    async def test_setup_registers_cog(self, pg_pool) -> None:
        bot = MagicMock()
        bot.pg_pool = pg_pool
        await counter_mod.setup(bot)
        bot.add_cog.assert_called_once()
        added = bot.add_cog.call_args[0][0]
        assert isinstance(added, Counter)
