"""Music controller buttons stay live the same way event posts do."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import nextcord

from main_bot.cogs.production.music import (
    _normalize_lavalink_youtube_url,
    MUSIC_CTRL_BACK,
    MUSIC_CTRL_NEXT,
    MUSIC_CTRL_QUEUE,
    MUSIC_CTRL_SHUFFLE,
    MUSIC_CTRL_STOP,
    MUSIC_CTRL_TOGGLE,
    MUSIC_GAMING_TOGGLE_PREFIX,
    GamingMixToggleView,
    MusicCog,
    MusicControlView,
)

_CTRL_IDS = (
    MUSIC_CTRL_BACK,
    MUSIC_CTRL_TOGGLE,
    MUSIC_CTRL_NEXT,
    MUSIC_CTRL_SHUFFLE,
    MUSIC_CTRL_STOP,
    MUSIC_CTRL_QUEUE,
)


def test_youtube_music_playlist_url_keeps_only_the_list_id():
    url = (
        "https://music.youtube.com/playlist?list=PLAUKKg_MbEAE_AyeAji1XoFuggiRn4ou9"
        "&si=qEZm3ttAxlNSoLIq&drli=1"
    )
    assert (
        _normalize_lavalink_youtube_url(url)
        == "https://www.youtube.com/playlist?list=PLAUKKg_MbEAE_AyeAji1XoFuggiRn4ou9"
    )


async def test_music_control_buttons_keep_the_same_ids():
    plain = MusicControlView(cog=MagicMock())
    highlighted = MusicControlView(cog=MagicMock(), shuffle_highlight=True)

    assert plain.timeout is None
    assert plain.is_persistent()
    assert highlighted.is_persistent()
    assert tuple(child.custom_id for child in plain.children) == _CTRL_IDS
    assert tuple(child.custom_id for child in highlighted.children) == _CTRL_IDS
    assert plain.shuffle.style == nextcord.ButtonStyle.secondary
    assert highlighted.shuffle.style == nextcord.ButtonStyle.success
    assert not hasattr(plain, "guild_id")


async def test_gaming_mix_buttons_keep_folder_ids():
    view = GamingMixToggleView(MagicMock(), ["risk-of-rain", "hades"], {"hades"})

    assert view.timeout is None
    assert view.is_persistent()
    assert [child.custom_id for child in view.children] == [
        f"{MUSIC_GAMING_TOGGLE_PREFIX}risk-of-rain",
        f"{MUSIC_GAMING_TOGGLE_PREFIX}hades",
    ]
    assert view.children[0].style == nextcord.ButtonStyle.secondary
    assert view.children[1].style == nextcord.ButtonStyle.success
    assert not hasattr(view, "guild_id")


async def test_gaming_toggle_reads_the_folder_from_the_button_id():
    cog = MagicMock()
    cog.handle_gaming_mix_toggle = AsyncMock()
    view = GamingMixToggleView(cog, ["hades"], set())
    interaction = MagicMock()
    interaction.guild.id = 99
    interaction.data = {"custom_id": f"{MUSIC_GAMING_TOGGLE_PREFIX}hades"}

    await view._toggle(interaction)

    cog.handle_gaming_mix_toggle.assert_awaited_once_with(99, interaction, "hades")


async def test_music_cog_registers_one_persistent_controller():
    cog = MusicCog.__new__(MusicCog)
    cog._persistent_views = []
    cog._persistent_views_stopped = False
    cog.bot = MagicMock()

    cog.register_persistent_views()

    registered = [call.args[0] for call in cog.bot.add_view.call_args_list]
    controllers = [view for view in registered if isinstance(view, MusicControlView)]
    assert len(controllers) == 1
    assert controllers[0].is_persistent()
    assert all(view.is_persistent() for view in registered)
