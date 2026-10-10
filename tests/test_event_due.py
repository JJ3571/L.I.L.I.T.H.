"""When an event's start time elapses, decide whether to ping attendees."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import nextcord

from types import SimpleNamespace

from main_bot.cogs.production.event2 import (
    Event,
    EventDeleteConfirmView,
    EventEditModal,
    EventManagementView,
    EventView,
    _EVENT_NOTIFY_GRACE,
    _to_timestamptz_arg,
    event_due_action,
    event_id_from_message,
    format_time_for_edit,
)


def test_future_event_is_pending():
    now = datetime.datetime(2026, 10, 10, 5, 40, tzinfo=datetime.timezone.utc)
    start = now + datetime.timedelta(minutes=5)
    assert event_due_action(start, now) == "pending"


def test_event_that_just_started_should_notify():
    now = datetime.datetime(2026, 10, 10, 5, 53, tzinfo=datetime.timezone.utc)
    start = datetime.datetime(2026, 10, 10, 5, 45, tzinfo=datetime.timezone.utc)
    assert event_due_action(start, now) == "notify"


def test_event_older_than_grace_expires_without_a_ping():
    now = datetime.datetime(2026, 10, 10, 5, 53, tzinfo=datetime.timezone.utc)
    start = now - _EVENT_NOTIFY_GRACE - datetime.timedelta(seconds=1)
    assert event_due_action(start, now) == "expire"


def test_event_id_is_read_from_the_embed_footer():
    message = SimpleNamespace(embeds=[SimpleNamespace(footer=SimpleNamespace(text="Event ID: 42"))])
    assert event_id_from_message(message) == 42
    assert event_id_from_message(SimpleNamespace(embeds=[])) is None


async def test_event_views_stay_registered_after_a_restart():
    cog = MagicMock()
    for view_cls in (EventView, EventManagementView, EventDeleteConfirmView):
        view = view_cls(cog)
        assert view.timeout is None
        assert view.is_persistent()
        assert all(child.custom_id for child in view.children)


def test_edit_form_uses_the_timezone_the_user_typed():
    stored = datetime.datetime(2026, 10, 10, 18, 0, tzinfo=datetime.timezone.utc)
    assert format_time_for_edit(stored, "PST") == "10/10/2026 11:00am PST"
    assert format_time_for_edit(stored, None) == "10/10/2026 6:00pm UTC"


def test_stored_timestamptz_can_be_compared_without_parsing_text():
    stored = datetime.datetime(2026, 10, 10, 7, 0, tzinfo=datetime.timezone.utc)
    assert _to_timestamptz_arg(stored) == stored


async def test_edit_event_modal_prefills_fields():
    modal = EventEditModal(
        cog=MagicMock(),
        event_id=5,
        current_name="Game night",
        current_description="Bring snacks",
        current_time="10/10/2026 19:00 UTC",
        current_max="8",
    )
    values = [child.default_value for child in modal.children]
    assert values == ["Game night", "10/10/2026 19:00 UTC", "Bring snacks", "8"]


def test_event_command_is_only_the_root_command():
    command = Event.event_command
    assert command.name == "event"
    assert command.children == {}


def test_naive_datetimes_are_treated_as_utc():
    now = datetime.datetime(2026, 10, 10, 5, 53)
    start = datetime.datetime(2026, 10, 10, 5, 45)
    assert event_due_action(start, now) == "notify"


def _notice_cog(channel, user):
    cog = Event.__new__(Event)
    cog.cog_print = MagicMock()
    cog.bot = MagicMock()
    cog.bot.get_channel.return_value = channel
    cog.bot.get_user.return_value = user
    return cog


async def test_notice_pings_channel_and_dms_each_user():
    channel = MagicMock()
    channel.send = AsyncMock()
    user = MagicMock()
    user.send = AsyncMock()
    cog = _notice_cog(channel, user)
    embed = nextcord.Embed(title="starting")

    delivered = await cog._deliver_notice(
        channel_id=111,
        mentions="<@222>",
        embed=embed,
        user_ids=[222],
        label="event 1",
    )

    assert delivered is True
    channel.send.assert_awaited_once()
    user.send.assert_awaited_once()
    assert channel.send.await_args.kwargs["content"] == "<@222>"
    assert user.send.await_args.kwargs["embed"] is embed


async def test_notice_still_dms_when_the_channel_post_fails():
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=RuntimeError("missing access"))
    user = MagicMock()
    user.send = AsyncMock()
    cog = _notice_cog(channel, user)

    delivered = await cog._deliver_notice(
        channel_id=111,
        mentions="<@222>",
        embed=nextcord.Embed(title="reminder"),
        user_ids=[222],
        label="reminder 4",
    )

    assert delivered is True
    user.send.assert_awaited_once()
