"""Unit tests for guild_settings helpers (no Discord API / no real pool)."""

from __future__ import annotations

from main_bot.guild_settings import (
    GuildSettings,
    SETTING_BY_KEY,
    env_value_is_nondefault,
    music_voice_denylist_ids,
    mtg_autolink_channel_ids,
    set_cached_settings,
)


def test_group_status_missing_by_default() -> None:
    gs = GuildSettings(1, {})
    set_cached_settings(gs)
    assert gs.group_status("birthday") == "missing"
    assert gs.group_status("roles") == "missing"


def test_group_status_skipped() -> None:
    gs = GuildSettings(1, {"skipped_groups": ["birthday", "mtg"]})
    assert gs.group_status("birthday") == "skipped"
    assert gs.is_group_skipped("mtg")


def test_group_status_configured_int() -> None:
    gs = GuildSettings(1, {"birthday_role_id": 42})
    assert gs.group_status("birthday") == "configured"


def test_roles_empty_list_is_configured() -> None:
    gs = GuildSettings(1, {"bot_admin_role_ids": []})
    assert gs.has("bot_admin_role_ids")
    assert gs.group_status("roles") == "configured"


def test_get_int_default() -> None:
    gs = GuildSettings(1, {})
    assert gs.get_int("bot_spam_id") == 0


def test_mtg_union_channels() -> None:
    gs = GuildSettings(
        1,
        {
            "mtg_autolink_channel_ids": [1, 2],
            "mtg_autolink_cooldown_channel_ids": [2, 3],
        },
    )
    set_cached_settings(gs)
    assert mtg_autolink_channel_ids(gs) == frozenset({1, 2, 3})


def test_music_denylist() -> None:
    gs = GuildSettings(1, {"music_voice_channel_denylist": [9]})
    set_cached_settings(gs)
    assert music_voice_denylist_ids(gs) == frozenset({9})


def test_env_value_is_nondefault() -> None:
    defn = SETTING_BY_KEY["bot_spam_id"]
    assert not env_value_is_nondefault(defn, 0)
    assert env_value_is_nondefault(defn, 123)
    list_defn = SETTING_BY_KEY["voice_channel_ids"]
    assert not env_value_is_nondefault(list_defn, [])
    assert env_value_is_nondefault(list_defn, [1])
