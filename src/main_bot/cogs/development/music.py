"""
Discord music cog: Lavalink (Wavelink) playback + local folder music + VC chat controls.

Requires ``discord`` → Nextcord aliasing in ``main.py`` before this cog imports Wavelink.
"""

from __future__ import annotations

import asyncio
import random
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Any, cast, Union

import nextcord
import wavelink
from nextcord import SlashOption
from nextcord.ext import commands
from wavelink import Playlist, TrackEndEventPayload, TrackStartEventPayload, WebsocketClosedEventPayload
from wavelink.enums import AutoPlayMode, DiscordVoiceCloseType, TrackSource
from wavelink.exceptions import InvalidNodeException, LavalinkLoadException, QueueEmpty

from main_bot.paths import PROJECT_ROOT
from main_bot.server_configs.config import (
    GUILD_ID,
    LAVALINK_PASSWORD,
    LAVALINK_URI,
    MUSIC_LOCAL_HTTP_HOST,
    MUSIC_LOCAL_HTTP_PORT,
    MUSIC_VOICE_CHANNEL_DENYLIST_IDS,
)
from main_bot.utils.jazz_http_server import LocalMusicHttpServer
from main_bot.utils.local_music_scan import list_audio_files

SessionKind = Literal["idle", "stream", "local_folder"]
LOCAL_MUSIC_ROOT = PROJECT_ROOT / "local_music"

BACK_RESTART_THRESHOLD_MS = 5000
RANDOM_START_END_MARGIN_MS = 30_000
DISCORD_ACTIVITY_MAX_LEN = 128
# Wavelink: no loaded track for this long → on_wavelink_inactive_player (see Player.inactive_timeout).
MUSIC_INACTIVE_PLAYER_TIMEOUT_SEC = 300
# Wavelink Node default resume_timeout=60 keeps Lavalink playing after the client websocket drops; 0 disables that.
MUSIC_LAVALINK_RESUME_TIMEOUT_SEC = 0
# ``Player.disconnect()`` waits on Lavalink HTTP teardown; if that stalls, Discord never gets a voice leave unless we send it ourselves.
MUSIC_DISCONNECT_LAVA_CLEANUP_TIMEOUT_SEC = 8.0
# Periodic sweep: if the bot is alone in the music VC (no non-bot listeners), force teardown.
MUSIC_ALONE_VOICE_SWEEP_INTERVAL_SEC = 30.0


def _presence_stream_line(track: wavelink.Playable) -> str:
    author = (getattr(track, "author", None) or "").strip()
    title = (getattr(track, "title", None) or "Unknown").strip()
    line = f"{author} - {title}" if author else title
    return line[:DISCORD_ACTIVITY_MAX_LEN]


def _presence_local_line(folder: str) -> str:
    label = folder.replace("_", " ").strip().capitalize()
    return f"Playing {label} music"[:DISCORD_ACTIVITY_MAX_LEN]


@dataclass(frozen=True)
class LocalFolderDefinition:
    """Slash name and ``local_music/{folder}`` are the same ``folder`` string."""

    folder: str
    shuffle_files_on_start: bool
    start_offset_policy: Literal["beginning", "random_ms"]


LOCAL_FOLDER_DEFS: dict[str, LocalFolderDefinition] = {
    "jazz": LocalFolderDefinition("jazz", True, "random_ms"),
    "lofi": LocalFolderDefinition("lofi", True, "random_ms"),
    "minecraft": LocalFolderDefinition("minecraft", True, "beginning"),
}


def _is_music_voice_channel_blocked(channel_id: int) -> bool:
    return channel_id in MUSIC_VOICE_CHANNEL_DENYLIST_IDS


def _human_members_in_voice_channel(guild: nextcord.Guild, channel_id: int, bot_user_id: int) -> int:
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


def _is_discord_unknown_message_error(exc: BaseException) -> bool:
    """True when a message operation failed because the message no longer exists (deleted, purged, etc.)."""
    if isinstance(exc, nextcord.NotFound):
        return True
    return getattr(exc, "code", None) == 10008


def _format_duration_ms(ms: int) -> str:
    seconds, _ms = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _unwrap_playables(search: wavelink.Search) -> list[wavelink.Playable]:
    if isinstance(search, Playlist):
        return list(search.tracks)
    return list(search) if search else []


def _looks_like_http_url(query: str) -> bool:
    p = urllib.parse.urlparse(query.strip())
    return bool(p.scheme in ("http", "https") and p.netloc)


def _normalize_lavalink_youtube_url(query: str) -> str:
    """Canonical hosts/query for Lavalink youtube-plugin (music.youtube playlist loads often need www.youtube)."""
    q = query.strip()
    p = urllib.parse.urlparse(q)
    if p.scheme not in ("http", "https") or not p.netloc:
        return q
    host = p.netloc.lower().split(":", 1)[0].removeprefix("[").removesuffix("]")
    youtube_hosts = frozenset(
        {"music.youtube.com", "www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be"},
    )
    if host not in youtube_hosts:
        return q
    pairs = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in pairs if k.lower() not in ("si", "feature", "pp")]
    new_query = urllib.parse.urlencode(filtered)
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
        if vid:
            return urllib.parse.urlunparse(
                ("https", "www.youtube.com", "/watch", "", urllib.parse.urlencode({"v": vid}), ""),
            )
    new_netloc = "www.youtube.com" if host in ("music.youtube.com", "m.youtube.com") else p.netloc
    return urllib.parse.urlunparse((p.scheme, new_netloc, p.path, p.params, new_query, p.fragment))


def _youtube_playlist_list_id(url: str) -> Optional[str]:
    p = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(p.query)
    ids = qs.get("list")
    if ids and ids[0]:
        return ids[0]
    return None


def _search_query_for_kind(query: str, kind: str) -> str:
    """Bias YouTube Music text search (Lavalink ytmsearch). Ignored for URLs."""
    q = query.strip()
    k = (kind or "auto").lower()
    if k == "auto":
        return q
    if k == "song":
        if len(q) >= 2 and q[0] == q[-1] == '"':
            return q
        return f'"{q}"'
    if k == "artist":
        return f"{q} artist"
    if k == "album":
        return f"{q} album"
    return q


def _is_playlist_style_youtube_url(url: str) -> bool:
    p = urllib.parse.urlparse(url.lower())
    if urllib.parse.parse_qs(p.query).get("list"):
        return True
    return p.path.rstrip("/").endswith("/playlist")


LOCAL_FOLDER_COVER_FILENAMES: tuple[str, ...] = ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp")


def _folder_static_cover_path(folder: str) -> Optional[Path]:
    """Return ``local_music/{folder}/cover.*`` if present (flat folder layout)."""
    root = LOCAL_MUSIC_ROOT / folder
    for name in LOCAL_FOLDER_COVER_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _local_cover_attachment_name(folder: str, path: Path) -> str:
    ext = (path.suffix or ".png").lower()
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in folder)[:64]
    return f"music_cover_{safe}{ext}"


@dataclass
class GuildMusicState:
    session: SessionKind = "idle"
    local_folder: Optional[str] = None
    local_remaining: list[Path] = field(default_factory=list)
    local_history_paths: list[Path] = field(default_factory=list)
    controller_message: Optional[nextcord.Message] = None
    shuffle_highlight: bool = False


def _embed_source_kind(state: GuildMusicState) -> str:
    """Short label for the status line (Streaming vs Local)."""
    if state.session == "stream":
        return "(Streaming from Web)"
    if state.session == "local_folder":
        return "(Local music)"
    return "Idle"


def build_music_embed_and_files(
    voice_player: wavelink.Player,
    state: GuildMusicState,
) -> tuple[nextcord.Embed, list[nextcord.File]]:
    """Build controller embed; attach static folder art files for local sessions when configured."""
    files: list[nextcord.File] = []
    cur = voice_player.current
    if cur is not None:
        if state.session == "local_folder":
            n_queued = len(state.local_remaining)
        elif state.session == "stream":
            n_queued = len(voice_player.queue)
        else:
            n_queued = 0
        dur_ms = getattr(cur, "length", 0) or 0
        dur_display = _format_duration_ms(int(dur_ms)) if dur_ms else "—"
        author_raw = (getattr(cur, "author", None) or "").strip()
        artist_display = author_raw if author_raw else "—"
        status = "Paused" if voice_player.paused else "Playing"
        source_kind = _embed_source_kind(state)
        body = (
            f"Track Name: **{cur.title}**\n"
            f"Artist: **{artist_display}**\n"
            f"Duration: **{dur_display}**"
        )
        footer_text = f"{status} - {source_kind}\nTracks Queued: {n_queued}"
    else:
        body = "*Nothing playing*"
        footer_text = ""
    title = "Now playing" if cur is not None else "Music"
    embed = nextcord.Embed(title=title, description=body, color=nextcord.Color.dark_teal())
    if footer_text:
        embed.set_footer(text=footer_text)

    if cur is not None:
        if state.session == "stream":
            art = getattr(cur, "artwork", None)
            if isinstance(art, str) and art.startswith(("http://", "https://")):
                embed.set_image(url=art)
        elif state.session == "local_folder" and state.local_folder:
            cover = _folder_static_cover_path(state.local_folder)
            if cover is not None:
                fname = _local_cover_attachment_name(state.local_folder, cover)
                embed.set_image(url=f"attachment://{fname}")
                files.append(nextcord.File(cover, filename=fname))

    return embed, files


class MusicControlView(nextcord.ui.View):
    """Voice controller; shuffle button style reflects ``GuildMusicState.shuffle_highlight``."""

    def __init__(self, cog: MusicCog, guild_id: int, *, shuffle_highlight: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

        shuffle_style = (
            nextcord.ButtonStyle.success if shuffle_highlight else nextcord.ButtonStyle.secondary
        )

        async def back_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_control_back(guild_id, interaction)

        async def toggle_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_control_toggle_pause(guild_id, interaction)

        async def next_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_control_next(guild_id, interaction)

        async def shuffle_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_control_shuffle(guild_id, interaction)

        async def stop_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_control_stop(guild_id, interaction)

        async def queue_cb(interaction: nextcord.Interaction) -> None:
            vc = cast(Optional[wavelink.Player], interaction.guild.voice_client if interaction.guild else None)
            state = cog.guild_states.get(guild_id)
            if not isinstance(vc, wavelink.Player) or vc.current is None:
                await interaction.response.send_message("Nothing playing.", ephemeral=True)
                return
            if state and state.session == "local_folder" and state.local_remaining:
                lines = [f"{i + 1}. {p.stem}" for i, p in enumerate(state.local_remaining[:15])]
                extra = ""
                if len(state.local_remaining) > 15:
                    extra = f"\n… and {len(state.local_remaining) - 15} more"
                await interaction.response.send_message(
                    "**Up Next**\n" + "\n".join(lines) + extra,
                    ephemeral=True,
                )
            elif vc.queue:
                lines = []
                for i, t in enumerate(list(vc.queue)[:15]):
                    lines.append(f"{i + 1}. {t.title}")
                extra = ""
                if len(vc.queue) > 15:
                    extra = f"\n… and {len(vc.queue) - 15} more"
                await interaction.response.send_message(
                    "**Up Next**\n" + "\n".join(lines) + extra,
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Now playing: **{vc.current.title}**\n(No tracks queued.)",
                    ephemeral=True,
                )

        b_back = nextcord.ui.Button(emoji="⏮️", style=nextcord.ButtonStyle.secondary, row=0)
        b_back.callback = back_cb
        b_toggle = nextcord.ui.Button(emoji="⏯️", style=nextcord.ButtonStyle.primary, row=0)
        b_toggle.callback = toggle_cb
        b_next = nextcord.ui.Button(emoji="⏭️", style=nextcord.ButtonStyle.secondary, row=0)
        b_next.callback = next_cb
        b_shuffle = nextcord.ui.Button(emoji="🔀", style=shuffle_style, row=0)
        b_shuffle.callback = shuffle_cb
        b_stop = nextcord.ui.Button(emoji="⏹️", style=nextcord.ButtonStyle.primary, row=0)
        b_stop.callback = stop_cb
        b_queue = nextcord.ui.Button(label="Up Next", style=nextcord.ButtonStyle.secondary, row=1)
        b_queue.callback = queue_cb

        self.add_item(b_back)
        self.add_item(b_toggle)
        self.add_item(b_next)
        self.add_item(b_shuffle)
        self.add_item(b_stop)
        self.add_item(b_queue)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            return False
        vc = interaction.guild.voice_client
        if not isinstance(vc, wavelink.Player) or not vc.connected:
            await interaction.response.send_message("Nothing is connected.", ephemeral=True)
            return False
        vc_ch = vc.channel
        if vc_ch is None:
            await interaction.response.send_message("Voice channel unavailable.", ephemeral=True)
            return False
        if _is_music_voice_channel_blocked(vc_ch.id):
            await interaction.response.send_message(
                "Music controls aren't available in this voice channel.",
                ephemeral=True,
            )
            return False
        member = interaction.user
        if member.bot:
            return False
        g = interaction.guild
        resolved = g.get_member(member.id) if g is not None else None
        if resolved is None:
            resolved = member
        if resolved.voice is None or resolved.voice.channel is None:
            await interaction.response.send_message("Join the bot's voice channel to use controls.", ephemeral=True)
            return False
        if resolved.voice.channel.id != vc_ch.id:
            await interaction.response.send_message("Use controls from the same voice channel.", ephemeral=True)
            return False
        return True


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_states: dict[int, GuildMusicState] = {}
        self._empty_disconnect_tasks: dict[int, asyncio.Task[None]] = {}
        self._alone_voice_sweep_task: Optional[asyncio.Task[None]] = None
        self._resume_rotating_after_music: bool = False
        allowed = frozenset(LOCAL_FOLDER_DEFS.keys())
        self._local_http = LocalMusicHttpServer(
            LOCAL_MUSIC_ROOT,
            allowed_folders=allowed,
            host=MUSIC_LOCAL_HTTP_HOST,
            port=MUSIC_LOCAL_HTTP_PORT,
        )
        print("MusicCog initialized")

    async def _start_music_background_services(self) -> None:
        """Nextcord does not run ``cog_load``; call this from :func:`setup` after :meth:`Bot.add_cog`."""
        try:
            await self._local_http.start()
            print(
                f"[music] Local music HTTP on http://{MUSIC_LOCAL_HTTP_HOST}:{MUSIC_LOCAL_HTTP_PORT}/"
                "{{jazz,lofi,minecraft}}/… — keep this bot running while Lavalink streams local files.",
            )
        except OSError as e:
            print(
                f"[music] Local music HTTP could not bind {MUSIC_LOCAL_HTTP_HOST}:{MUSIC_LOCAL_HTTP_PORT}: {e}. "
                "Local folder slash commands will fail until this port is available.",
            )
        loop = asyncio.get_running_loop()
        try:
            loop.create_task(self._warm_lavalink_background())
        except RuntimeError:
            pass
        if self._alone_voice_sweep_task is None or self._alone_voice_sweep_task.done():
            try:
                self._alone_voice_sweep_task = loop.create_task(self._alone_in_voice_sweep_loop())
            except RuntimeError:
                pass

    def _stop_music_background_services(self) -> None:
        """Call from extension :func:`teardown` — Nextcord does not run ``cog_unload``."""
        for gid in list(self._empty_disconnect_tasks.keys()):
            self._cancel_empty_disconnect(gid)
        t = self._alone_voice_sweep_task
        if t is not None and not t.done():
            t.cancel()
        self._alone_voice_sweep_task = None
        try:
            self.bot.loop.create_task(self._local_http.stop())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if not isinstance(vc, wavelink.Player) or not vc.connected:
                continue
            if vc.current is None and not vc.queue and not vc.paused:
                try:
                    await vc.disconnect()
                except Exception as e:
                    print(f"[music] on_ready idle disconnect {guild.id}: {e}")

    def _cancel_empty_disconnect(self, guild_id: int) -> None:
        task = self._empty_disconnect_tasks.pop(guild_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _schedule_disconnect_if_empty(self, guild_id: int, bot_vc_id: int) -> None:
        self._cancel_empty_disconnect(guild_id)

        async def _run() -> None:
            try:
                await asyncio.sleep(2.0)
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    return
                player = self._resolve_wavelink_player(guild_id)
                if player is None or player.channel is None or player.channel.id != bot_vc_id:
                    return
                if _human_members_in_voice_channel(guild, bot_vc_id, self.bot.user.id) == 0:
                    await self.full_disconnect_guild(guild_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[music] empty-channel disconnect task: {e}")
            finally:
                self._empty_disconnect_tasks.pop(guild_id, None)

        self._empty_disconnect_tasks[guild_id] = asyncio.create_task(_run())

    def _guild_has_music_voice_session(self, guild: nextcord.Guild) -> bool:
        if isinstance(guild.voice_client, wavelink.Player):
            return True
        if self._resolve_wavelink_player(guild.id) is not None:
            return True
        st = self.guild_states.get(guild.id)
        return st is not None and st.session != "idle"

    def _music_voice_channel_id(self, guild: nextcord.Guild) -> Optional[int]:
        vc = guild.voice_client
        if isinstance(vc, wavelink.Player) and vc.channel is not None:
            return vc.channel.id
        pl = self._resolve_wavelink_player(guild.id)
        if pl is not None and pl.channel is not None:
            return pl.channel.id
        me = guild.me
        if me is None or me.voice is None or me.voice.channel is None:
            return None
        ch = me.voice.channel
        if isinstance(ch, (nextcord.VoiceChannel, nextcord.StageChannel)):
            return ch.id
        return None

    async def _alone_in_voice_sweep_loop(self) -> None:
        # Do not use ``wait_until_ready`` here: this task may start while ``on_ready`` is still running.
        try:
            while True:
                if not self.bot.is_ready():
                    await asyncio.sleep(1.0)
                    continue
                try:
                    for guild in list(self.bot.guilds):
                        try:
                            if not self._guild_has_music_voice_session(guild):
                                continue
                            ch_id = self._music_voice_channel_id(guild)
                            if ch_id is None:
                                continue
                            if _is_music_voice_channel_blocked(ch_id):
                                continue
                            if _human_members_in_voice_channel(guild, ch_id, self.bot.user.id) > 0:
                                continue
                            await self.full_disconnect_guild(guild.id)
                        except Exception as e:
                            print(f"[music] alone-voice sweep guild={guild.id}: {e}")
                except Exception as e:
                    print(f"[music] alone-voice sweep: {e}")
                await asyncio.sleep(MUSIC_ALONE_VOICE_SWEEP_INTERVAL_SEC)
        except asyncio.CancelledError:
            raise

    def _get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id]

    def _status_cog(self):
        return self.bot.get_cog("BotStatusCog")

    def _maybe_pause_rotating_for_music(self) -> None:
        cog = self._status_cog()
        if cog is None:
            return
        if cog.pause_rotating_status_if_running():
            self._resume_rotating_after_music = True

    async def _sync_music_presence(self, preferred_guild_id: Optional[int] = None) -> None:
        ordered_ids: list[int] = []
        if preferred_guild_id is not None:
            ordered_ids.append(preferred_guild_id)
        for g in self.bot.guilds:
            if g.id not in ordered_ids:
                ordered_ids.append(g.id)

        for gid in ordered_ids:
            guild = self.bot.get_guild(gid)
            if guild is None:
                continue
            vc = guild.voice_client
            if not isinstance(vc, wavelink.Player) or not vc.connected:
                continue
            state = self.guild_states.get(gid)
            if state is None:
                continue
            cur = vc.current
            if cur is None:
                continue
            if state.session == "stream":
                self._maybe_pause_rotating_for_music()
                line = _presence_stream_line(cur)
                await self.bot.change_presence(
                    activity=nextcord.Activity(type=nextcord.ActivityType.listening, name=line),
                )
                return
            if state.session == "local_folder" and state.local_folder:
                self._maybe_pause_rotating_for_music()
                line = _presence_local_line(state.local_folder)
                await self.bot.change_presence(
                    activity=nextcord.Activity(type=nextcord.ActivityType.listening, name=line),
                )
                return

        resume = self._resume_rotating_after_music
        self._resume_rotating_after_music = False
        cog = self._status_cog()
        if cog is not None and resume:
            await cog.resume_rotating_status_if_was_running(True)
        else:
            await self.bot.change_presence(activity=None)

    async def _warm_lavalink_background(self) -> None:
        """Connect to Lavalink after startup so the first voice session avoids node WS + JVM cold start."""
        await asyncio.sleep(1.5)
        try:
            if await self._ensure_lavalink():
                print("[music] Lavalink node warmed up in the background.")
        except Exception as e:
            print(f"[music] Lavalink warmup (non-fatal): {e}")

    async def _slash_reply(
        self,
        interaction: nextcord.Interaction,
        content: str,
    ) -> None:
        """Single reply for deferred slash commands (avoids extra follow-up messages)."""
        try:
            await interaction.edit_original_message(content=content)
        except (nextcord.HTTPException, nextcord.NotFound) as e:
            print(f"_slash_reply: {e}")
            try:
                await interaction.followup.send(content, ephemeral=False)
            except Exception:
                pass

    async def _wait_for_pool_connected(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                wavelink.Pool.get_node()
                return True
            except InvalidNodeException:
                await asyncio.sleep(0.05)
        return False

    async def _ensure_lavalink(self) -> bool:
        try:
            wavelink.Pool.get_node()
            return True
        except InvalidNodeException:
            pass

        try:
            await wavelink.Pool.reconnect()
        except Exception as e:
            print(f"Lavalink Pool.reconnect: {e}")

        if await self._wait_for_pool_connected():
            return True

        await wavelink.Pool.connect(
            nodes=[
                wavelink.Node(
                    uri=LAVALINK_URI,
                    password=LAVALINK_PASSWORD,
                    client=self.bot,
                    inactive_player_timeout=MUSIC_INACTIVE_PLAYER_TIMEOUT_SEC,
                    resume_timeout=MUSIC_LAVALINK_RESUME_TIMEOUT_SEC,
                )
            ],
            client=self.bot,
        )

        if await self._wait_for_pool_connected():
            return True

        print(
            f"Lavalink has no CONNECTED node at {LAVALINK_URI} (timed out waiting for WS ready). "
            "Start Lavalink before music commands; confirm LAVALINK_PASSWORD matches application.yml."
        )
        return False

    async def _local_http_track_url(self, folder: str, path: Path) -> str:
        await self._local_http.start()
        return self._local_http.url_for_file(folder, path)

    async def _connect_voice(self, guild: nextcord.Guild, voice_channel: nextcord.VoiceChannel) -> Optional[wavelink.Player]:
        if not await self._ensure_lavalink():
            return None
        vc = guild.voice_client
        if isinstance(vc, wavelink.Player):
            if vc.channel and vc.channel.id == voice_channel.id:
                vc.autoplay = AutoPlayMode.partial
                return vc
            await vc.move_to(voice_channel)
            vc.autoplay = AutoPlayMode.partial
            return vc
        if vc is not None:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        try:
            player = await voice_channel.connect(
                cls=wavelink.Player,
                timeout=30.0,
                reconnect=True,
            )
            pl = cast(wavelink.Player, player)
            pl.autoplay = AutoPlayMode.partial
            return pl
        except Exception as e:
            print(f"Voice connect failed: {e}")
            return None

    def _resolve_wavelink_player(self, guild_id: int) -> Optional[wavelink.Player]:
        """Guild ``voice_client`` can disagree with Lavalink's player registry; prefer both."""
        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            vc = guild.voice_client
            if isinstance(vc, wavelink.Player):
                return vc
        try:
            node = wavelink.Pool.get_node()
        except InvalidNodeException:
            return None
        return node.get_player(guild_id)

    async def full_disconnect_guild(self, guild_id: int) -> None:
        self._cancel_empty_disconnect(guild_id)
        state = self.guild_states.get(guild_id)
        msg = state.controller_message if state else None
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        if state:
            state.controller_message = None
            state.session = "idle"
            state.local_folder = None
            state.local_remaining.clear()
            state.local_history_paths.clear()

        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            vc = guild.voice_client
            pl: Optional[wavelink.Player] = vc if isinstance(vc, wavelink.Player) else None
            if pl is None:
                pl = self._resolve_wavelink_player(guild_id)
            try:
                await guild.change_voice_state(channel=None)
            except Exception as e:
                print(f"[music] change_voice_state(channel=None): {e}")
            if pl is not None:
                try:
                    await asyncio.wait_for(pl.disconnect(), timeout=MUSIC_DISCONNECT_LAVA_CLEANUP_TIMEOUT_SEC)
                except TimeoutError:
                    print(
                        "[music] Player.disconnect timed out (voice leave was already sent); "
                        "Lavalink may need a restart if playback ghosts."
                    )
                except Exception as e:
                    print(f"[music] Player.disconnect: {e}")

        self.guild_states.pop(guild_id, None)
        await self._sync_music_presence()

    async def _recover_controller_message(self, guild_id: int) -> None:
        """If the stored controller message was deleted, post a new one while playback is still active."""
        state = self.guild_states.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not state or guild is None:
            return
        vc = guild.voice_client
        if not isinstance(vc, wavelink.Player) or not vc.connected:
            return
        ch = vc.channel
        if ch is None or not isinstance(ch, (nextcord.VoiceChannel, nextcord.StageChannel)):
            return
        if state.session == "stream":
            if vc.current is None and not vc.queue:
                return
        elif state.session == "local_folder":
            if not state.local_folder and vc.current is None:
                return
        else:
            return
        if await self.upsert_controller(ch, vc):
            print(f"[music] reposted controller (previous message missing) guild={guild_id}")

    async def refresh_controller_embed(self, guild_id: int) -> None:
        state = self.guild_states.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not state or not state.controller_message or guild is None:
            return
        vc = guild.voice_client
        if not isinstance(vc, wavelink.Player):
            return
        try:
            embed, ctrl_files = build_music_embed_and_files(vc, state)
            view = build_music_control_view(self, guild_id)
            edit_kw: dict[str, Any] = {"embed": embed, "view": view, "attachments": []}
            if ctrl_files:
                edit_kw["files"] = ctrl_files
            await state.controller_message.edit(**edit_kw)
        except (nextcord.NotFound, nextcord.HTTPException) as e:
            state.controller_message = None
            if _is_discord_unknown_message_error(e):
                await self._recover_controller_message(guild_id)
            else:
                print(f"refresh_controller_embed: {e}")
        except Exception as e:
            print(f"refresh_controller_embed: {e}")

    async def _edit_control_message(self, interaction: nextcord.Interaction, guild_id: int) -> None:
        """Acknowledge the interaction, then edit the stored controller message.

        Defer + :meth:`nextcord.Message.edit` keeps the UI view registered correctly; using
        :meth:`interaction.response.edit_message` alone can leave buttons dead after updates.
        """
        guild = self.bot.get_guild(guild_id)
        state = self.guild_states.get(guild_id)
        if guild is None or state is None or state.controller_message is None:
            await interaction.response.send_message("Nothing to update.", ephemeral=True)
            return
        vc = guild.voice_client
        if not isinstance(vc, wavelink.Player):
            await interaction.response.send_message("No active player.", ephemeral=True)
            return
        embed, ctrl_files = build_music_embed_and_files(vc, state)
        view = build_music_control_view(self, guild_id)
        await interaction.response.defer()
        try:
            edit_kw = {"embed": embed, "view": view, "attachments": []}
            if ctrl_files:
                edit_kw["files"] = ctrl_files
            await state.controller_message.edit(**edit_kw)
        except (nextcord.NotFound, nextcord.HTTPException) as e:
            state.controller_message = None
            if _is_discord_unknown_message_error(e):
                await self._recover_controller_message(guild_id)
            else:
                print(f"_edit_control_message: {e}")
        except Exception as e:
            print(f"_edit_control_message: {e}")

    async def handle_control_toggle_pause(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        vc = cast(Optional[wavelink.Player], interaction.guild.voice_client if interaction.guild else None)
        if not isinstance(vc, wavelink.Player) or vc.current is None:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        await vc.pause(not vc.paused)
        await self._edit_control_message(interaction, guild_id)

    async def handle_control_stop(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer()
        await self.full_disconnect_guild(guild_id)

    async def handle_control_next(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        guild = self.bot.get_guild(guild_id)
        state = self.guild_states.get(guild_id)
        vc = guild.voice_client if guild else None
        if not isinstance(vc, wavelink.Player) or state is None:
            await interaction.response.send_message("No session.", ephemeral=True)
            return
        if state.session == "local_folder":
            ok = await self._advance_local_manual(vc, state)
            if not ok:
                if guild_id not in self.guild_states:
                    await interaction.response.send_message("Playback finished.", ephemeral=True)
                else:
                    await interaction.response.send_message("Could not load the next track.", ephemeral=True)
                return
            await self._edit_control_message(interaction, guild_id)
            return
        if not vc.queue:
            await interaction.response.send_message("Nothing queued.", ephemeral=True)
            return
        try:
            next_track = vc.queue.get()
        except QueueEmpty:
            await interaction.response.send_message("Nothing queued.", ephemeral=True)
            return
        # skip() ends with reason "replaced"; wavelink autoplay ignores that and does not dequeue.
        await vc.play(next_track, replace=True)
        await self._edit_control_message(interaction, guild_id)

    async def handle_control_shuffle(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        guild = self.bot.get_guild(guild_id)
        state = self.guild_states.get(guild_id)
        vc = guild.voice_client if guild else None
        if not isinstance(vc, wavelink.Player) or state is None:
            await interaction.response.send_message("No session.", ephemeral=True)
            return
        if state.session == "local_folder":
            if state.shuffle_highlight:
                state.shuffle_highlight = False
                await self._edit_control_message(interaction, guild_id)
                return
            if not state.local_remaining:
                await interaction.response.send_message("Nothing left to shuffle.", ephemeral=True)
                return
            random.shuffle(state.local_remaining)
            ok = await self._advance_local_manual(vc, state)
            if not ok:
                if guild_id not in self.guild_states:
                    await interaction.response.send_message("Playback finished.", ephemeral=True)
                else:
                    await interaction.response.send_message("Could not advance.", ephemeral=True)
                return
            state.shuffle_highlight = True
            await self._edit_control_message(interaction, guild_id)
            return
        if state.shuffle_highlight:
            state.shuffle_highlight = False
            await self._edit_control_message(interaction, guild_id)
            return
        if not vc.queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        vc.queue.shuffle()
        state.shuffle_highlight = True
        await self._edit_control_message(interaction, guild_id)

    async def handle_control_back(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        guild = self.bot.get_guild(guild_id)
        state = self.guild_states.get(guild_id)
        vc = guild.voice_client if guild else None
        if not isinstance(vc, wavelink.Player) or state is None or vc.current is None:
            await interaction.response.send_message("Nothing playing.", ephemeral=True)
            return

        pos = vc.position
        if pos >= BACK_RESTART_THRESHOLD_MS:
            await vc.seek(0)
            await self._edit_control_message(interaction, guild_id)
            return

        if state.session == "stream":
            await self._stream_back(vc, interaction, guild_id)
            return

        if state.session == "local_folder" and state.local_folder:
            await self._local_back(vc, state, interaction, guild_id)
            return

        await vc.seek(0)
        await self._edit_control_message(interaction, guild_id)

    async def _stream_back(self, vc: wavelink.Player, interaction: nextcord.Interaction, guild_id: int) -> None:
        hist = vc.queue.history
        if hist is None or len(hist) < 2:
            await vc.seek(0)
            await self._edit_control_message(interaction, guild_id)
            return
        cur = vc.current
        if cur is None:
            return
        try:
            del hist[len(hist) - 1]
            prev = hist[len(hist) - 1]
            del hist[len(hist) - 1]
        except (IndexError, TypeError):
            await vc.seek(0)
            await self._edit_control_message(interaction, guild_id)
            return
        vc.queue.put_at(0, cur)
        await vc.play(prev, replace=True)
        await self._edit_control_message(interaction, guild_id)

    async def _local_back(
        self,
        vc: wavelink.Player,
        state: GuildMusicState,
        interaction: nextcord.Interaction,
        guild_id: int,
    ) -> None:
        folder = state.local_folder
        if not folder or len(state.local_history_paths) < 2:
            await vc.seek(0)
            await self._edit_control_message(interaction, guild_id)
            return
        cur_path = state.local_history_paths.pop()
        prev_path = state.local_history_paths[-1] if state.local_history_paths else None
        state.local_remaining.insert(0, cur_path)
        if prev_path is None:
            await vc.seek(0)
            await self._edit_control_message(interaction, guild_id)
            return
        ok = await self._play_local_path(
            vc,
            state,
            folder,
            prev_path,
            start_ms=0,
            append_history=False,
        )
        if not ok:
            await interaction.response.send_message("Could not load previous track.", ephemeral=True)
            return
        await self._edit_control_message(interaction, guild_id)

    def _random_start_ms(self, playable: wavelink.Playable) -> int:
        length = int(getattr(playable, "length", 0) or 0)
        if length <= RANDOM_START_END_MARGIN_MS:
            return 0
        return random.randint(0, length - RANDOM_START_END_MARGIN_MS)

    async def _play_local_path(
        self,
        player: wavelink.Player,
        state: GuildMusicState,
        folder: str,
        path: Path,
        *,
        start_ms: int = 0,
        append_history: bool = True,
    ) -> bool:
        try:
            url = await self._local_http_track_url(folder, path)
            tracks = await wavelink.Pool.fetch_tracks(url)
        except Exception as e:
            print(f"local track load failed: {e}")
            return False
        if not tracks:
            return False
        t0 = start_ms
        if t0 == 0 and folder in LOCAL_FOLDER_DEFS:
            if LOCAL_FOLDER_DEFS[folder].start_offset_policy == "random_ms":
                t0 = self._random_start_ms(tracks[0])
        try:
            await player.play(tracks[0], start=t0, replace=True)
        except Exception as e:
            print(f"local play failed: {e}")
            return False
        if append_history:
            state.local_history_paths.append(path)
        return True

    async def _advance_local_manual(self, player: wavelink.Player, state: GuildMusicState) -> bool:
        folder = state.local_folder
        if not folder or state.session != "local_folder":
            return False
        gid = player.guild.id if player.guild else None
        if not state.local_remaining:
            if gid is not None:
                await self.full_disconnect_guild(gid)
            return False
        next_path = state.local_remaining.pop(0)
        ok = await self._play_local_path(player, state, folder, next_path, start_ms=0)
        if not ok and gid is not None:
            await self.full_disconnect_guild(gid)
        return ok

    async def _continue_local_on_natural_finish(self, player: wavelink.Player, state: GuildMusicState) -> None:
        guild_id = player.guild.id if player.guild else None
        if guild_id is None:
            return
        if not state.local_remaining:
            await self.full_disconnect_guild(guild_id)
            return
        next_path = state.local_remaining.pop(0)
        folder = state.local_folder or ""
        ok = await self._play_local_path(player, state, folder, next_path, start_ms=0)
        if ok:
            await self.refresh_controller_embed(guild_id)
        else:
            await self.full_disconnect_guild(guild_id)

    async def upsert_controller(
        self,
        voice_channel: nextcord.VoiceChannel | nextcord.StageChannel,
        vc: wavelink.Player,
    ) -> bool:
        guild_id = voice_channel.guild.id
        state = self._get_state(guild_id)
        if state.controller_message:
            try:
                await state.controller_message.delete()
            except Exception:
                pass
            state.controller_message = None

        embed, ctrl_files = build_music_embed_and_files(vc, state)
        view = build_music_control_view(self, guild_id)
        try:
            send_kw: dict[str, Any] = {"embed": embed, "view": view}
            if ctrl_files:
                send_kw["files"] = ctrl_files
            state.controller_message = await voice_channel.send(**send_kw)
            return True
        except Exception as e:
            print(f"Could not post controller to VC chat: {e}")
            state.controller_message = None
            return False

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, _payload: TrackStartEventPayload) -> None:
        player = _payload.player
        if player is None or player.guild is None:
            return
        await self.refresh_controller_embed(player.guild.id)
        await self._sync_music_presence(player.guild.id)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        guild = player.guild
        if guild is None:
            return
        print(f"[music] inactive player timeout ({MUSIC_INACTIVE_PLAYER_TIMEOUT_SEC}s) — disconnecting guild={guild.id}")
        await self.full_disconnect_guild(guild.id)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: TrackEndEventPayload) -> None:
        player = payload.player
        if player is None or player.guild is None:
            return
        guild_id = player.guild.id
        state = self.guild_states.get(guild_id)
        if state is None:
            return

        reason = (payload.reason or "").lower()
        if reason != "finished":
            return

        if state.session == "local_folder":
            await self._continue_local_on_natural_finish(player, state)
            return

        if state.session == "stream":
            # Wavelink clears `player.current` before scheduling AutoPlay's `play()` for the
            # next track. Refreshing the controller immediately often shows "Nothing playing".
            # Worse: that Discord edit is async and can complete *after* `on_wavelink_track_start`
            # refreshes with the new track, leaving a stale blank embed until the next interaction.
            await asyncio.sleep(0)
            if player.current is not None or player.queue:
                return
            await self.refresh_controller_embed(guild_id)
            await self._sync_music_presence(player.guild.id)
            return

        await self.refresh_controller_embed(guild_id)

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: WebsocketClosedEventPayload) -> None:
        gid = payload.player.guild.id if payload.player and payload.player.guild else None
        code = payload.code
        print(
            f"[music] Lavalink Discord voice WS closed: guild={gid} "
            f"code={code.value} ({code.name}) reason={payload.reason!r} by_remote={payload.by_remote}",
        )
        if code == DiscordVoiceCloseType.DAVE_PROTOCOL_REQUIRED:
            print(
                "[music] 4017 DAVE: Discord requires E2EE voice. Lavalink 4.2+ includes DAVE via Koe/libdave — "
                "stay on current Lavalink; ensure Wavelink forwards voice payloads with channelId (you have 3.5.x). "
                "If this persists, check Lavalink logs/koe TRACE (lavalink.dev changelog v4.2.x) and Lavalink Discord.",
            )

    async def _fetch_tracks_for_music_play(self, query: str, *, search_kind: str = "auto") -> list[wavelink.Playable]:
        """Resolve Lavalink load for /music play: canonical YouTube URLs + YouTube Music text search."""
        raw = query.strip()
        if _looks_like_http_url(raw):
            load_url = _normalize_lavalink_youtube_url(raw)
            search = await wavelink.Playable.search(load_url)
            tracks = _unwrap_playables(search)
            if len(tracks) <= 1 and _is_playlist_style_youtube_url(load_url):
                lid = _youtube_playlist_list_id(load_url)
                if lid:
                    canonical = f"https://www.youtube.com/playlist?list={lid}"
                    try:
                        search2 = await wavelink.Playable.search(canonical)
                        t2 = _unwrap_playables(search2)
                        if len(t2) > len(tracks):
                            tracks = t2
                    except LavalinkLoadException:
                        pass
            return tracks
        adjusted = _search_query_for_kind(raw, search_kind)
        search = await wavelink.Playable.search(adjusted, source=TrackSource.YouTubeMusic)
        return _unwrap_playables(search)

    @nextcord.slash_command(name="music", description="Music player commands", guild_ids=[GUILD_ID])
    async def music(self, interaction: nextcord.Interaction) -> None:
        pass

    @music.subcommand(name="play", description="Play from streaming link or search for a song/album/artist.")
    async def music_play(
        self,
        interaction: nextcord.Interaction,
        query: str = SlashOption(description="Song URL or search query"),
        search_kind: str = SlashOption(
            description="Searching for... song name, artist, album.",
            choices=["auto", "song", "artist", "album"],
            default="auto",
        ),
        songs_to_play: int = SlashOption(
            name="songs",
            description="Songs to take from search (1 = top match). Ignored for playlist URLs.",
            min_value=1,
            max_value=15,
            default=1,
        ),
    ) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await self._slash_reply(interaction, "This command can only be used in a server.")
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await self._slash_reply(interaction, "You need to be in a voice channel to use this command!")
            return

        voice_channel = interaction.user.voice.channel
        if _is_music_voice_channel_blocked(voice_channel.id):
            await self._slash_reply(
                interaction,
                "Music bot can't be used in this voice channel! Join a different voice channel.",
            )
            return

        guild = interaction.guild

        if not await self._ensure_lavalink():
            await self._slash_reply(
                interaction,
                f"Could not reach Lavalink at `{LAVALINK_URI}`. Start Lavalink v4 and check LAVALINK_URI / LAVALINK_PASSWORD.",
            )
            return

        vc = await self._connect_voice(guild, voice_channel)
        if vc is None:
            await self._slash_reply(interaction, "Could not connect to voice.")
            return

        state = self._get_state(guild.id)
        state.session = "stream"
        state.local_folder = None
        state.local_remaining.clear()
        state.local_history_paths.clear()
        state.shuffle_highlight = False
        vc.queue.reset()

        is_url_query = _looks_like_http_url(query.strip())
        try:
            tracks = await self._fetch_tracks_for_music_play(query, search_kind=search_kind)
        except LavalinkLoadException as e:
            await self._slash_reply(interaction, f"Lavalink could not load that query: {e}")
            return
        except InvalidNodeException:
            await self._slash_reply(
                interaction,
                "No Lavalink node is connected. Ensure Lavalink v4 is running and credentials match.",
            )
            return
        except Exception as e:
            await self._slash_reply(interaction, f"Search error: {e}")
            return

        if not tracks:
            await self._slash_reply(interaction, "No song found!")
            return

        if is_url_query:
            if len(tracks) > 1:
                vc.queue.put(tracks[1:])
        elif songs_to_play > 1 and len(tracks) > 1:
            end = min(songs_to_play, len(tracks))
            more = tracks[1:end]
            if more:
                vc.queue.put(more)

        try:
            await vc.play(tracks[0])
        except Exception as e:
            await self._slash_reply(interaction, f"Playback failed: {e}")
            return

        posted = await self.upsert_controller(voice_channel, vc)
        extra = ""
        if not posted:
            extra = " Could not post the controller in the voice channel — check bot permissions there."
        await self._sync_music_presence(guild.id)
        await self._slash_reply(
            interaction,
            f"Playing in {voice_channel.mention}. Track info and controls are in that channel's chat.{extra}",
        )

    @music.subcommand(name="stop", description="Disconnect the bot from voice and clear the session")
    async def music_disconnect(self, interaction: nextcord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        await self.full_disconnect_guild(guild.id)
        await interaction.response.send_message("Disconnected from voice channel.")

    async def _start_local_folder_session(
        self,
        interaction: nextcord.Interaction,
        definition: LocalFolderDefinition,
    ) -> None:
        folder = definition.folder
        audio_dir = LOCAL_MUSIC_ROOT / folder
        paths = list_audio_files(audio_dir)
        if not paths:
            await self._slash_reply(
                interaction,
                f"No audio files found in `{audio_dir}`. Add `.mp3`/`.flac`/etc. to that folder.",
            )
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await self._slash_reply(interaction, "You need to be in a voice channel to use this command!")
            return

        voice_channel = interaction.user.voice.channel
        if _is_music_voice_channel_blocked(voice_channel.id):
            await self._slash_reply(
                interaction,
                "Music bot can't be used from this voice channel. Join a different voice channel.",
            )
            return

        guild = interaction.guild
        assert guild is not None

        if not await self._ensure_lavalink():
            await self._slash_reply(
                interaction,
                f"Could not reach Lavalink at `{LAVALINK_URI}`. Start Lavalink v4 and check LAVALINK_URI / LAVALINK_PASSWORD.",
            )
            return

        vc = await self._connect_voice(guild, voice_channel)
        if vc is None:
            await self._slash_reply(interaction, "Could not connect to voice.")
            return

        if definition.shuffle_files_on_start:
            random.shuffle(paths)
        first = paths[0]
        remaining = paths[1:]

        state = self._get_state(guild.id)
        state.session = "local_folder"
        state.local_folder = folder
        state.local_remaining = remaining
        state.local_history_paths.clear()
        state.shuffle_highlight = False
        vc.queue.reset()

        try:
            url = await self._local_http_track_url(folder, first)
            tracks = await wavelink.Pool.fetch_tracks(url)
        except OSError as e:
            state.session = "idle"
            state.local_folder = None
            state.local_remaining.clear()
            await self._slash_reply(
                interaction,
                f"Could not start loopback HTTP for `{MUSIC_LOCAL_HTTP_HOST}:{MUSIC_LOCAL_HTTP_PORT}`: {e}",
            )
            return
        except LavalinkLoadException as e:
            state.session = "idle"
            state.local_folder = None
            state.local_remaining.clear()
            await self._slash_reply(
                interaction,
                "Lavalink could not load local tracks over HTTP. Ensure ``sources.http: true`` in Lavalink "
                f"`application.yml`.\nDetail: {e}",
            )
            return

        if not tracks:
            state.session = "idle"
            state.local_folder = None
            state.local_remaining.clear()
            await self._slash_reply(
                interaction,
                "Could not decode tracks (empty Lavalink response). Confirm `sources.http: true` and try another format.",
            )
            return

        start_ms = 0
        if definition.start_offset_policy == "random_ms":
            start_ms = self._random_start_ms(tracks[0])

        try:
            await vc.play(tracks[0], start=start_ms)
        except Exception as e:
            state.session = "idle"
            state.local_folder = None
            state.local_remaining.clear()
            await self._slash_reply(interaction, f"Playback failed: {e}")
            return

        state.local_history_paths.append(first)

        posted = await self.upsert_controller(voice_channel, vc)
        extra = ""
        if not posted:
            extra = " Could not post the controller in the voice channel — check permissions there."
        await self._sync_music_presence(guild.id)
        label = folder
        await self._slash_reply(
            interaction,
            f"**/{label}** started in {voice_channel.mention} ({len(paths)} tracks). Use the controller message in that channel.{extra}",
        )

    @nextcord.slash_command(name="jazz", description="Shuffle and play tracks from local_music/jazz", guild_ids=[GUILD_ID])
    async def jazz_slash(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await self._slash_reply(interaction, "This command can only be used in a server.")
            return
        await self._start_local_folder_session(interaction, LOCAL_FOLDER_DEFS["jazz"])

    @nextcord.slash_command(name="lofi", description="Shuffle and play tracks from local_music/lofi", guild_ids=[GUILD_ID])
    async def lofi_slash(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await self._slash_reply(interaction, "This command can only be used in a server.")
            return
        await self._start_local_folder_session(interaction, LOCAL_FOLDER_DEFS["lofi"])

    @nextcord.slash_command(
        name="minecraft",
        description="Shuffle and play tracks from local_music/minecraft",
        guild_ids=[GUILD_ID],
    )
    async def minecraft_slash(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await self._slash_reply(interaction, "This command can only be used in a server.")
            return
        await self._start_local_folder_session(interaction, LOCAL_FOLDER_DEFS["minecraft"])

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: nextcord.Member, before: nextcord.VoiceState, after: nextcord.VoiceState) -> None:
        guild = member.guild
        player = self._resolve_wavelink_player(guild.id)
        bot_ch: Optional[Union[nextcord.VoiceChannel, nextcord.StageChannel]] = None
        if player is not None and player.channel is not None:
            bot_ch = player.channel
        elif guild.me and guild.me.voice and guild.me.voice.channel is not None:
            ch = guild.me.voice.channel
            if isinstance(ch, (nextcord.VoiceChannel, nextcord.StageChannel)):
                bot_ch = ch
        if bot_ch is None:
            return

        bot_vc = bot_ch

        if (
            before.channel is not None
            and after.channel is not None
            and before.channel.id == bot_vc.id
            and after.channel.id == bot_vc.id
        ):
            return

        if member.bot:
            return
        if after.channel is not None and after.channel.id == bot_vc.id:
            if before.channel is None or before.channel.id != bot_vc.id:
                self._cancel_empty_disconnect(guild.id)
                state = self.guild_states.get(guild.id)
                if state is not None and state.controller_message is not None:
                    await self.refresh_controller_embed(guild.id)
            return

        if before.channel is None or before.channel.id != bot_vc.id:
            return
        if after.channel is not None and after.channel.id == bot_vc.id:
            return
        self._schedule_disconnect_if_empty(guild.id, bot_vc.id)


def build_music_control_view(cog: MusicCog, guild_id: int) -> MusicControlView:
    state = cog.guild_states.get(guild_id)
    hl = state.shuffle_highlight if state else False
    return MusicControlView(cog, guild_id, shuffle_highlight=hl)


async def setup(bot: commands.Bot) -> None:
    cog = MusicCog(bot)
    bot.add_cog(cog)
    await cog._start_music_background_services()
    print("MusicCog has been added to the bot.")


def teardown(bot: commands.Bot) -> None:
    cog = bot.get_cog("MusicCog")
    if isinstance(cog, MusicCog):
        cog._stop_music_background_services()
