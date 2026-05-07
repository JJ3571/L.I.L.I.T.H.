"""Shared Discord voice helpers (gateway-accurate human counts, HTTP message errors)."""

from __future__ import annotations

import nextcord


def human_members_in_voice_channel(guild: nextcord.Guild, channel_id: int, bot_user_id: int) -> int:
    """Count non-bot accounts Discord still lists as connected to ``channel_id``.

    Uses ``guild._voice_states`` (gateway truth) instead of ``VoiceChannel.voice_states`` so we
    do not depend on channel cache objects. ``bot_user_id`` should be ``bot.user.id``.
    """
    n = 0
    for uid, vs in guild._voice_states.items():
        ch = vs.channel
        if ch is None or ch.id != channel_id:
            continue
        if uid == bot_user_id:
            continue
        member = guild.get_member(uid)
        if member is not None and member.bot:
            continue
        n += 1
    return n


def is_discord_unknown_message_error(exc: BaseException) -> bool:
    """True when a message operation failed because the message no longer exists (deleted, purged, etc.)."""
    if isinstance(exc, nextcord.NotFound):
        return True
    return getattr(exc, "code", None) == 10008
