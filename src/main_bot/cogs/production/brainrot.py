"""Random short SFX bursts in voice via Lavalink (DAVE-compatible); mutually exclusive with streaming/local music."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import nextcord
import wavelink
from nextcord import SlashOption
from nextcord.ext import commands
from wavelink.exceptions import InvalidNodeException, LavalinkLoadException

from main_bot.cogs.production.music import MUSIC_DISCONNECT_LAVA_CLEANUP_TIMEOUT_SEC

from main_bot.paths import LOCAL_AUDIO_ROOT, PROJECT_ROOT
from main_bot.server_configs.config import (
    GUILD_ID,
    MUSIC_VOICE_CHANNEL_DENYLIST_IDS,
    coin_emoji_id,
)
from main_bot.utils.discord_voice import human_members_in_voice_channel

_LOG = logging.getLogger("nextcord.brainrot")


def _brainrot_wavelink_pool_ids() -> str:
    try:
        nodes = getattr(wavelink.Pool, "nodes", None)
        if not nodes:
            return "(empty)"
        return ",".join(str(k) for k in nodes.keys())
    except Exception as e:
        return f"(nodes err: {e})"


BRAINROT_FOLDER = "brainrot"
# Random hard cap for “must fire by” deadline each gap (hidden from UI).
BRAINROT_SILENCE_CAP_MIN_SEC = 180.0  # 3 minutes
BRAINROT_SILENCE_CAP_MAX_SEC = 1200.0  # 20 minutes
BRAINROT_MIN_GAP_SEC = 30.0
BRAINROT_MAX_GAP_SEC = 180.0
BRAINROT_ESCALATION_SEC = 60.0
BRAINROT_BASE_DODGEBALLS = 1
BRAINROT_MAX_DODGEBALLS = 1
BRAINROT_SFX_COST = 50
BRAINROT_EMPTY_DISCONNECT_DELAY_SEC = 2.0
BRAINROT_ALONE_SWEEP_INTERVAL_SEC = 30.0

DODGEBALL_FILE = "dodgeball.mp3"
PLANKTON_FILE = "plankton.mp3"
STEEL_PIPE_FILE = "steel_pipe.mp3"
SMOKE_DETECTOR_FILE = "smoke_detector.mp3"


def brainrot_purchase_button_emoji() -> Union[str, nextcord.PartialEmoji]:
    """Guild ``coin`` emoji when ``COIN_EMOJI_ID`` is set; else Unicode coin."""
    if coin_emoji_id:
        return nextcord.PartialEmoji(name="coin", id=coin_emoji_id)
    return "\U0001FA99"


def brainrot_asset_dir() -> Path:
    return (LOCAL_AUDIO_ROOT / BRAINROT_FOLDER).resolve()


def roll_brainrot_silence_cap_sec(rng: random.Random) -> float:
    """Sample max silence before a forced burst for the current gap (not shown in the embed)."""
    lo = min(BRAINROT_SILENCE_CAP_MIN_SEC, BRAINROT_SILENCE_CAP_MAX_SEC)
    hi = max(BRAINROT_SILENCE_CAP_MIN_SEC, BRAINROT_SILENCE_CAP_MAX_SEC)
    return rng.uniform(lo, hi)


def schedule_next_wake_seconds(
    rng: random.Random,
    *,
    now_mono: float,
    deadline_mono: float,
    min_gap_sec: float,
    max_gap_sec: float,
) -> float:
    """Seconds to sleep before the next scheduler wake; never overshoots ``deadline_mono``."""
    remaining = deadline_mono - now_mono
    if remaining <= 0:
        return 0.0
    lo = min(min_gap_sec, max_gap_sec)
    hi = max(min_gap_sec, max_gap_sec)
    sampled = rng.uniform(lo, hi)
    return min(sampled, remaining)


def dodgeball_burst_count(
    elapsed_since_last_trigger_sec: float,
    *,
    base: int = BRAINROT_BASE_DODGEBALLS,
    escalation_sec: float = BRAINROT_ESCALATION_SEC,
    max_dodgeballs: int = BRAINROT_MAX_DODGEBALLS,
) -> int:
    extra = int(elapsed_since_last_trigger_sec // escalation_sec)
    return max(1, min(max_dodgeballs, base + extra))


def build_burst_paths(
    rng: random.Random,
    *,
    elapsed_since_last_trigger_sec: float,
    dodgeball_path: Path,
    plankton_path: Path,
    steel_pipe_path: Path,
    smoke_detector_path: Path,
    pending_plankton: int,
    pending_pipe: int,
    pending_smoke: int = 0,
) -> list[Path]:
    n = dodgeball_burst_count(elapsed_since_last_trigger_sec)
    seq: list[Path] = [dodgeball_path] * n
    seq.extend([plankton_path] * pending_plankton)
    seq.extend([steel_pipe_path] * pending_pipe)
    seq.extend([smoke_detector_path] * pending_smoke)
    rng.shuffle(seq)
    return seq


def _is_voice_channel_blocked(channel_id: int) -> bool:
    return channel_id in MUSIC_VOICE_CHANNEL_DENYLIST_IDS


def _path_display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


@dataclass
class BrainrotSession:
    rng: random.Random
    voice_channel_id: int
    last_trigger_mono: float
    silence_cap_sec: float
    pending_plankton: int = 0
    pending_pipe: int = 0
    pending_smoke: int = 0
    controller_message: Optional[nextcord.Message] = None
    loop_task: Optional[asyncio.Task[None]] = None
    dodgeball_path: Path = field(default_factory=lambda: brainrot_asset_dir() / DODGEBALL_FILE)
    plankton_path: Path = field(default_factory=lambda: brainrot_asset_dir() / PLANKTON_FILE)
    steel_pipe_path: Path = field(default_factory=lambda: brainrot_asset_dir() / STEEL_PIPE_FILE)
    smoke_detector_path: Path = field(default_factory=lambda: brainrot_asset_dir() / SMOKE_DETECTOR_FILE)


class BrainrotControlView(nextcord.ui.View):
    def __init__(self, cog: BrainrotCog, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

        plankton_btn = nextcord.ui.Button(
            label=f"[{BRAINROT_SFX_COST}] - Plankton",
            emoji=brainrot_purchase_button_emoji(),
            style=nextcord.ButtonStyle.secondary,
            row=0,
        )

        async def plankton_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_buy_plankton(guild_id, interaction)

        plankton_btn.callback = plankton_cb

        pipe_btn = nextcord.ui.Button(
            label=f"[{BRAINROT_SFX_COST}] - Steel pipe",
            emoji=brainrot_purchase_button_emoji(),
            style=nextcord.ButtonStyle.secondary,
            row=0,
        )

        async def pipe_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_buy_pipe(guild_id, interaction)

        pipe_btn.callback = pipe_cb

        smoke_btn = nextcord.ui.Button(
            label=f"[{BRAINROT_SFX_COST}] - Smoke detector",
            emoji=brainrot_purchase_button_emoji(),
            style=nextcord.ButtonStyle.secondary,
            row=0,
        )

        async def smoke_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_buy_smoke_detector(guild_id, interaction)

        smoke_btn.callback = smoke_cb

        stop_btn = nextcord.ui.Button(label="Stop", style=nextcord.ButtonStyle.danger, row=1)

        async def stop_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_stop_button(guild_id, interaction)

        stop_btn.callback = stop_cb

        self.add_item(plankton_btn)
        self.add_item(pipe_btn)
        self.add_item(smoke_btn)
        self.add_item(stop_btn)


class BrainrotCog(commands.Cog):
    """Brainrot voice SFX scheduler."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sessions: dict[int, BrainrotSession] = {}
        self._empty_disconnect_tasks: dict[int, asyncio.Task[None]] = {}
        self._alone_sweep_task: Optional[asyncio.Task[None]] = None

    def _music_cog_for_brainrot(self) -> Optional[commands.Cog]:
        """Return the bot's Music cog if it exposes brainrot hooks.

        Do not use ``isinstance(..., MusicCog)``: some runtimes (duplicate package roots, mixed
        ``src`` vs site-packages imports) register a working cog whose class object is not
        identical to the one this module imported, so ``isinstance`` lies.
        """

        cog = self.bot.get_cog("MusicCog")
        if cog is None:
            return None
        if not callable(getattr(cog, "brainrot_connect_voice", None)):
            return None
        if not callable(getattr(cog, "brainrot_sfx_http_url", None)):
            return None
        return cog

    def is_session_active(self, guild_id: int) -> bool:
        return guild_id in self._sessions

    def _music_blocking_brainrot(self, guild: nextcord.Guild) -> Optional[str]:
        music = self.bot.get_cog("MusicCog")
        if music is None:
            return None
        fn = getattr(music, "_guild_has_music_voice_session", None)
        if callable(fn) and fn(guild):
            return "Music is active. Use `/music stop` before starting brainrot."
        return None

    def _cancel_empty_disconnect(self, guild_id: int) -> None:
        task = self._empty_disconnect_tasks.pop(guild_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _schedule_disconnect_if_empty(self, guild_id: int, bot_vc_id: int) -> None:
        self._cancel_empty_disconnect(guild_id)

        async def _run() -> None:
            try:
                await asyncio.sleep(BRAINROT_EMPTY_DISCONNECT_DELAY_SEC)
                guild = self.bot.get_guild(guild_id)
                if guild is None or guild_id not in self._sessions:
                    return
                if human_members_in_voice_channel(guild, bot_vc_id, self.bot.user.id) == 0:
                    await self._full_stop(guild_id, disconnect_voice=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _LOG.warning("brainrot empty-channel disconnect task: %s", e)
            finally:
                self._empty_disconnect_tasks.pop(guild_id, None)

        self._empty_disconnect_tasks[guild_id] = asyncio.create_task(_run())

    def _brainrot_voice_channel_id(self, guild: nextcord.Guild) -> Optional[int]:
        me = guild.me
        if me is None or me.voice is None or me.voice.channel is None:
            return None
        ch = me.voice.channel
        if isinstance(ch, (nextcord.VoiceChannel, nextcord.StageChannel)):
            return ch.id
        return None

    async def _alone_in_voice_sweep_loop(self) -> None:
        try:
            while True:
                if self.bot.is_ready():
                    for guild in list(self.bot.guilds):
                        try:
                            if guild.id not in self._sessions:
                                continue
                            ch_id = self._brainrot_voice_channel_id(guild)
                            if ch_id is None:
                                continue
                            if _is_voice_channel_blocked(ch_id):
                                continue
                            if human_members_in_voice_channel(guild, ch_id, self.bot.user.id) > 0:
                                continue
                            await self._full_stop(guild.id, disconnect_voice=True)
                        except Exception as e:
                            _LOG.warning("brainrot alone sweep guild=%s: %s", guild.id, e)
                await asyncio.sleep(BRAINROT_ALONE_SWEEP_INTERVAL_SEC)
        except asyncio.CancelledError:
            raise

    async def _slash_reply(self, interaction: nextcord.Interaction, content: str) -> None:
        try:
            await interaction.edit_original_message(content=content)
        except (nextcord.HTTPException, nextcord.NotFound):
            try:
                await interaction.followup.send(content, ephemeral=False)
            except Exception:
                pass

    def _embed_for_session(self, guild_id: int) -> nextcord.Embed:
        sess = self._sessions.get(guild_id)
        pend_p = sess.pending_plankton if sess else 0
        pend_sp = sess.pending_pipe if sess else 0
        pend_sm = sess.pending_smoke if sess else 0
        body = (
            "Silence… possibly interrupted.\n\n"
            f"**Pending extras:** plankton ×{pend_p}, steel pipe ×{pend_sp}, smoke detector ×{pend_sm}\n"
            f"Purchases apply to the **next** burst ({BRAINROT_SFX_COST} coins each)."
        )
        embed = nextcord.Embed(title="Brainrot", description=body, color=nextcord.Color.dark_grey())
        embed.set_footer(text="(Uses Lavalink. Cannot be used at the same time as /music.)")
        return embed

    def _brainrot_player(self, guild: nextcord.Guild) -> Optional[wavelink.Player]:
        vc = guild.voice_client
        if isinstance(vc, wavelink.Player):
            return vc
        try:
            node = wavelink.Pool.get_node()
        except InvalidNodeException:
            return None
        pl = node.get_player(guild.id)
        return pl if isinstance(pl, wavelink.Player) else None

    async def refresh_controller(self, guild_id: int) -> None:
        sess = self._sessions.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        if sess is None or guild is None or sess.controller_message is None:
            return
        pl = self._brainrot_player(guild)
        if pl is None or not pl.connected:
            return
        try:
            embed = self._embed_for_session(guild_id)
            view = BrainrotControlView(self, guild_id)
            await sess.controller_message.edit(embed=embed, view=view)
        except Exception as e:
            _LOG.warning("brainrot refresh_controller: %s", e)

    async def handle_buy_plankton(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        sess = self._sessions.get(guild_id)
        if sess is None:
            await interaction.followup.send("No active brainrot session.", ephemeral=True)
            return
        path = sess.plankton_path
        if not path.is_file():
            await interaction.followup.send(f"Missing `{_path_display(path)}`.", ephemeral=True)
            return
        economy = self.bot.get_cog("Economy")
        if economy is None:
            await interaction.followup.send("Economy is unavailable.", ephemeral=True)
            return
        uid = interaction.user.id
        balance = await economy.get_user_balance(uid)
        if balance < BRAINROT_SFX_COST:
            await interaction.followup.send(
                f"You need {BRAINROT_SFX_COST} coins (balance: {balance}).",
                ephemeral=True,
            )
            return
        ok = await economy.deduct_user_balance(uid, BRAINROT_SFX_COST)
        if not ok:
            await interaction.followup.send("Could not deduct coins.", ephemeral=True)
            return
        sess.pending_plankton += 1
        await self.refresh_controller(guild_id)

    async def handle_buy_pipe(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        sess = self._sessions.get(guild_id)
        if sess is None:
            await interaction.followup.send("No active brainrot session.", ephemeral=True)
            return
        path = sess.steel_pipe_path
        if not path.is_file():
            await interaction.followup.send(f"Missing `{_path_display(path)}`.", ephemeral=True)
            return
        economy = self.bot.get_cog("Economy")
        if economy is None:
            await interaction.followup.send("Economy is unavailable.", ephemeral=True)
            return
        uid = interaction.user.id
        balance = await economy.get_user_balance(uid)
        if balance < BRAINROT_SFX_COST:
            await interaction.followup.send(
                f"You need {BRAINROT_SFX_COST} coins (balance: {balance}).",
                ephemeral=True,
            )
            return
        ok = await economy.deduct_user_balance(uid, BRAINROT_SFX_COST)
        if not ok:
            await interaction.followup.send("Could not deduct coins.", ephemeral=True)
            return
        sess.pending_pipe += 1
        await self.refresh_controller(guild_id)

    async def handle_buy_smoke_detector(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        sess = self._sessions.get(guild_id)
        if sess is None:
            await interaction.followup.send("No active brainrot session.", ephemeral=True)
            return
        path = sess.smoke_detector_path
        if not path.is_file():
            await interaction.followup.send(f"Missing `{_path_display(path)}`.", ephemeral=True)
            return
        economy = self.bot.get_cog("Economy")
        if economy is None:
            await interaction.followup.send("Economy is unavailable.", ephemeral=True)
            return
        uid = interaction.user.id
        balance = await economy.get_user_balance(uid)
        if balance < BRAINROT_SFX_COST:
            await interaction.followup.send(
                f"You need {BRAINROT_SFX_COST} coins (balance: {balance}).",
                ephemeral=True,
            )
            return
        ok = await economy.deduct_user_balance(uid, BRAINROT_SFX_COST)
        if not ok:
            await interaction.followup.send("Could not deduct coins.", ephemeral=True)
            return
        sess.pending_smoke += 1
        await self.refresh_controller(guild_id)

    async def handle_stop_button(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if guild_id not in self._sessions:
            await interaction.followup.send("Nothing to stop.", ephemeral=True)
            return
        await self._full_stop(guild_id, disconnect_voice=True)
        await interaction.followup.send("Brainrot stopped.", ephemeral=True)

    async def _lavalink_play_sfx(self, player: wavelink.Player, path: Path) -> None:
        music_cog = self._music_cog_for_brainrot()
        if music_cog is None:
            raise RuntimeError("MusicCog is required for brainrot playback.")
        gid = player.guild.id if player.guild else 0
        _LOG.info("brainrot sfx begin guild=%s file=%s pool=%s", gid, path.name, _brainrot_wavelink_pool_ids())
        url = await music_cog.brainrot_sfx_http_url(path)
        try:
            tracks = await wavelink.Pool.fetch_tracks(url)
        except LavalinkLoadException as e:
            _LOG.warning(
                "brainrot Lavalink load failed guild=%s file=%s url_host=%s err=%s",
                gid,
                path.name,
                urlsplit(url).netloc or "?",
                e,
                exc_info=True,
            )
            raise
        if not tracks:
            _LOG.warning(
                "brainrot Lavalink empty track response guild=%s file=%s url_host=%s",
                gid,
                path.name,
                urlsplit(url).netloc or "?",
            )
            raise RuntimeError(f"Lavalink returned no track for {path.name}")
        await player.play(tracks[0], replace=True)
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            cur = player.current
            playing = bool(getattr(player, "playing", False))
            if cur is None and not playing:
                break
        else:
            _LOG.warning("brainrot sfx wait timed out: %s", path)

    async def _scheduler_loop(self, guild_id: int) -> None:
        try:
            while guild_id in self._sessions:
                sess = self._sessions[guild_id]
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    await self._full_stop(guild_id, disconnect_voice=False)
                    return
                player = self._brainrot_player(guild)
                if player is None or not player.connected:
                    await self._full_stop(guild_id, disconnect_voice=False)
                    return

                now = time.monotonic()
                deadline = sess.last_trigger_mono + sess.silence_cap_sec
                delay = schedule_next_wake_seconds(
                    sess.rng,
                    now_mono=now,
                    deadline_mono=deadline,
                    min_gap_sec=BRAINROT_MIN_GAP_SEC,
                    max_gap_sec=BRAINROT_MAX_GAP_SEC,
                )
                await asyncio.sleep(delay)

                if guild_id not in self._sessions:
                    return

                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    await self._full_stop(guild_id, disconnect_voice=False)
                    return
                player = self._brainrot_player(guild)
                if player is None or not player.connected:
                    await self._full_stop(guild_id, disconnect_voice=False)
                    return

                sess = self._sessions[guild_id]
                elapsed = time.monotonic() - sess.last_trigger_mono
                burst = build_burst_paths(
                    sess.rng,
                    elapsed_since_last_trigger_sec=elapsed,
                    dodgeball_path=sess.dodgeball_path,
                    plankton_path=sess.plankton_path,
                    steel_pipe_path=sess.steel_pipe_path,
                    smoke_detector_path=sess.smoke_detector_path,
                    pending_plankton=sess.pending_plankton,
                    pending_pipe=sess.pending_pipe,
                    pending_smoke=sess.pending_smoke,
                )
                sess.pending_plankton = 0
                sess.pending_pipe = 0
                sess.pending_smoke = 0

                try:
                    for p in burst:
                        if guild_id not in self._sessions:
                            return
                        guild = self.bot.get_guild(guild_id)
                        if guild is None:
                            await self._full_stop(guild_id, disconnect_voice=False)
                            return
                        player = self._brainrot_player(guild)
                        if player is None or not player.connected:
                            await self._full_stop(guild_id, disconnect_voice=False)
                            return
                        await self._lavalink_play_sfx(player, p)
                except Exception as e:
                    _LOG.warning("brainrot burst playback guild=%s: %s", guild_id, e)

                sess.last_trigger_mono = time.monotonic()
                sess.silence_cap_sec = roll_brainrot_silence_cap_sec(sess.rng)
                await self.refresh_controller(guild_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("brainrot scheduler guild=%s", guild_id)
            if guild_id in self._sessions:
                await self._full_stop(guild_id, disconnect_voice=True)

    async def _cleanup_session_record(self, guild_id: int, *, disconnect_voice: bool) -> None:
        """Remove session metadata and optionally disconnect Lavalink voice."""
        self._cancel_empty_disconnect(guild_id)
        sess = self._sessions.pop(guild_id, None)
        if sess is None:
            return
        msg = sess.controller_message
        if msg:
            try:
                await msg.edit(view=None)
            except Exception:
                pass
            try:
                await msg.delete()
            except Exception:
                pass

        if disconnect_voice:
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                pl: Optional[wavelink.Player] = (
                    guild.voice_client if isinstance(guild.voice_client, wavelink.Player) else None
                )
                if pl is None:
                    try:
                        node = wavelink.Pool.get_node()
                        cand = node.get_player(guild_id)
                        pl = cand if isinstance(cand, wavelink.Player) else None
                    except InvalidNodeException:
                        pl = None
                try:
                    await guild.change_voice_state(channel=None)
                except Exception as e:
                    _LOG.warning("brainrot change_voice_state: %s", e)
                if pl is not None:
                    try:
                        await asyncio.wait_for(pl.disconnect(), timeout=MUSIC_DISCONNECT_LAVA_CLEANUP_TIMEOUT_SEC)
                    except TimeoutError:
                        _LOG.warning("brainrot Player.disconnect timed out guild=%s", guild_id)
                    except Exception as e:
                        _LOG.warning("brainrot disconnect: %s", e)

    async def _full_stop(self, guild_id: int, *, disconnect_voice: bool) -> None:
        sess = self._sessions.get(guild_id)
        if sess is None:
            return
        if sess.loop_task and not sess.loop_task.done():
            sess.loop_task.cancel()
            try:
                await sess.loop_task
            except asyncio.CancelledError:
                pass
        await self._cleanup_session_record(guild_id, disconnect_voice=disconnect_voice)

    async def _after_bot_left_voice_cleanup(self, guild_id: int) -> None:
        if guild_id not in self._sessions:
            return
        sess = self._sessions[guild_id]
        if sess.loop_task and not sess.loop_task.done():
            sess.loop_task.cancel()
            try:
                await sess.loop_task
            except asyncio.CancelledError:
                pass
        await self._cleanup_session_record(guild_id, disconnect_voice=False)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: nextcord.Member,
        before: nextcord.VoiceState,
        after: nextcord.VoiceState,
    ) -> None:
        if member.id == self.bot.user.id:
            if before.channel is not None and after.channel is None:
                gid = before.channel.guild.id
                if gid in self._sessions:
                    asyncio.create_task(self._after_bot_left_voice_cleanup(gid))
            return

        guild = member.guild
        if guild.id not in self._sessions:
            return

        bot_ch_id = self._brainrot_voice_channel_id(guild)
        if bot_ch_id is None:
            return

        if member.bot:
            return

        if after.channel is not None and after.channel.id == bot_ch_id:
            if before.channel is None or before.channel.id != bot_ch_id:
                self._cancel_empty_disconnect(guild.id)
                await self.refresh_controller(guild.id)
            return

        if before.channel is None or before.channel.id != bot_ch_id:
            return
        if after.channel is not None and after.channel.id == bot_ch_id:
            return

        self._schedule_disconnect_if_empty(guild.id, bot_ch_id)

    @nextcord.slash_command(name="brainrot", description="Random silence-breaking SFX in voice", guild_ids=[GUILD_ID])
    async def brainrot_group(self, interaction: nextcord.Interaction) -> None:
        pass

    @brainrot_group.subcommand(name="start", description="Join your voice channel and start brainrot")
    async def brainrot_start(
        self,
        interaction: nextcord.Interaction,
        seed: Optional[int] = SlashOption(description="RNG seed (optional)", required=False, default=None),
    ) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await self._slash_reply(interaction, "This command can only be used in a server.")
            return

        guild = interaction.guild

        blocked = self._music_blocking_brainrot(guild)
        if blocked:
            await self._slash_reply(interaction, blocked)
            return

        if guild.id in self._sessions:
            await self._slash_reply(interaction, "Brainrot is already running. Use `/brainrot stop` first.")
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await self._slash_reply(interaction, "You need to be in a voice channel.")
            return

        voice_channel = interaction.user.voice.channel
        if not isinstance(voice_channel, (nextcord.VoiceChannel, nextcord.StageChannel)):
            await self._slash_reply(interaction, "Unsupported channel type.")
            return

        if _is_voice_channel_blocked(voice_channel.id):
            await self._slash_reply(interaction, "This voice channel is blocked for voice bots.")
            return

        _LOG.info(
            "brainrot slash start guild=%s user=%s voice_ch=%s seed_fixed=%s wavelink_registered=%s",
            guild.id,
            interaction.user.id,
            voice_channel.id,
            seed is not None,
            _brainrot_wavelink_pool_ids(),
        )

        asset_root = brainrot_asset_dir()
        dodge_path = asset_root / DODGEBALL_FILE
        plank_path = asset_root / PLANKTON_FILE
        pipe_path = asset_root / STEEL_PIPE_FILE
        smoke_path = asset_root / SMOKE_DETECTOR_FILE

        if not dodge_path.is_file():
            await self._slash_reply(
                interaction,
                f"Missing `{_path_display(dodge_path)}`. Add dodgeball.mp3 under local_audio/brainrot.",
            )
            return

        rng = random.Random(seed) if seed is not None else random.Random()

        music_cog = self._music_cog_for_brainrot()
        if music_cog is None:
            await self._slash_reply(interaction, "Music cog is not loaded — brainrot needs Lavalink + loopback HTTP from music.")
            return

        player = await music_cog.brainrot_connect_voice(guild, voice_channel)
        if player is None:
            snap = music_cog._music_voice_snapshot(guild)
            _LOG.warning(
                "brainrot_start voice/Lavalink connect failed guild=%s wavelink_registered=%s %s",
                guild.id,
                _brainrot_wavelink_pool_ids(),
                snap,
            )
            await self._slash_reply(
                interaction,
                "Could not reach Lavalink or join voice. Start Lavalink (matching LAVALINK_URI / LAVALINK_PASSWORD) and try again.",
            )
            return

        _LOG.info(
            "brainrot_start connected guild=%s voice_ch=%s player_connected=%s",
            guild.id,
            voice_channel.id,
            getattr(player, "connected", None),
        )

        mono = time.monotonic()
        cap = roll_brainrot_silence_cap_sec(rng)
        sess = BrainrotSession(
            rng=rng,
            voice_channel_id=voice_channel.id,
            last_trigger_mono=mono,
            silence_cap_sec=cap,
            dodgeball_path=dodge_path,
            plankton_path=plank_path,
            steel_pipe_path=pipe_path,
            smoke_detector_path=smoke_path,
        )
        self._sessions[guild.id] = sess

        embed = self._embed_for_session(guild.id)
        view = BrainrotControlView(self, guild.id)
        try:
            msg = await voice_channel.send(embed=embed, view=view)
            sess.controller_message = msg
        except Exception as e:
            await self._full_stop(guild.id, disconnect_voice=True)
            await self._slash_reply(interaction, f"Could not post controller: {e}")
            return

        sess.loop_task = asyncio.create_task(self._scheduler_loop(guild.id))
        await self._slash_reply(interaction, "Brainrot started.")

    @brainrot_group.subcommand(name="stop", description="Stop brainrot and leave voice")
    async def brainrot_stop(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer()
        if interaction.guild is None:
            await self._slash_reply(interaction, "This command can only be used in a server.")
            return
        gid = interaction.guild.id
        if gid not in self._sessions:
            await self._slash_reply(interaction, "Brainrot is not active.")
            return
        _LOG.info(
            "brainrot slash stop guild=%s user=%s wavelink_registered=%s",
            gid,
            getattr(interaction.user, "id", 0),
            _brainrot_wavelink_pool_ids(),
        )
        await self._full_stop(gid, disconnect_voice=True)
        await self._slash_reply(interaction, "Brainrot stopped.")

    async def cog_unload(self) -> None:
        if self._alone_sweep_task and not self._alone_sweep_task.done():
            self._alone_sweep_task.cancel()
            try:
                await self._alone_sweep_task
            except asyncio.CancelledError:
                pass
            self._alone_sweep_task = None
        for gid in list(self._sessions.keys()):
            await self._full_stop(gid, disconnect_voice=True)


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("BrainrotCog") is not None:
        return
    cog = BrainrotCog(bot)
    bot.add_cog(cog)
    cog._alone_sweep_task = asyncio.get_running_loop().create_task(cog._alone_in_voice_sweep_loop())


def teardown(bot: commands.Bot) -> None:
    cog = bot.get_cog("BrainrotCog")
    if isinstance(cog, BrainrotCog) and cog._alone_sweep_task and not cog._alone_sweep_task.done():
        cog._alone_sweep_task.cancel()
