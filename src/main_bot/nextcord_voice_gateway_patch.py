"""Patch PyPI nextcord voice WebSocket URL from ``/?v=4`` to ``/?v=8``.

**4006** ("Session is no longer valid") — Often caused by connecting with the legacy
gateway version; PyPI nextcord 3.1.1 still uses ``/?v=4`` while current Discord media
servers expect **v8** for the initial WebSocket URL.

**4017** ("E2EE/DAVE protocol required") — Discord closes the voice WebSocket if the
client does not implement **DAVE** (Discord Audio Video End-to-End encryption).
``discord.py`` **2.7+** negotiates DAVE when the optional **`davey`** package is
installed (``discord.py[voice]``). **nextcord does not implement DAVE** (even on
GitHub master as of this writing), so voice connections can fail with **4017** after
moving to gateway v8 — there is nothing this small URL patch can do for that; fixing
it requires either upstream nextcord to port discord.py’s voice/DAVE stack, moving the
bot to ``discord.py``, or using an out-of-process voice solution (e.g. Lavalink).

Remove this shim after a nextcord release ships ``/?v=8`` *and* DAVE support (if you
still use nextcord).

References:

- https://github.com/nextcord/nextcord/pull/1264 (v8 URL / 4006 class of issues)
- Voice close **4017**: Discord API ``VoiceCloseCodes.EndToEndEncryptionDAVEProtocolRequired``
- https://github.com/Rapptz/discord.py (voice + ``davey``)
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from nextcord.gateway import DiscordVoiceWebSocket
from nextcord.voice_client import VoiceClient


def apply_nextcord_voice_gateway_v8_patch() -> None:
    """Replace ``DiscordVoiceWebSocket.from_client`` with the v=8 gateway URL."""

    @classmethod
    async def from_client(
        cls,
        client: VoiceClient,
        *,
        resume: bool = False,
        hook: Optional[Callable[..., Any]] = None,
    ) -> DiscordVoiceWebSocket:
        gateway = f"wss://{client.endpoint}/?v=8"
        http = client._state.http
        socket = await http.ws_connect(gateway, compress=15)
        ws = cls(socket, loop=client.loop, hook=hook)
        ws.gateway = gateway
        ws._connection = client
        ws._max_heartbeat_timeout = 60.0
        ws.thread_id = threading.get_ident()

        if resume:
            await ws.resume()
        else:
            await ws.identify()

        return ws

    DiscordVoiceWebSocket.from_client = from_client  # type: ignore[method-assign]
