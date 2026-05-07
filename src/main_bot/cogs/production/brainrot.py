"""Random short SFX bursts in voice; native FFmpeg playback (mutually exclusive with music / Lavalink)."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import nextcord
import wavelink
from nextcord import SlashOption
from nextcord.ext import commands

from main_bot.paths import LOCAL_AUDIO_ROOT, PROJECT_ROOT
from main_bot.server_configs.config import GUILD_ID, MUSIC_VOICE_CHANNEL_DENYLIST_IDS
from main_bot.utils.discord_voice import human_members_in_voice_channel

_LOG = logging.getLogger("nextcord.brainrot")

BRAINROT_FOLDER = "brainrot"
BRAINROT_MAX_SILENCE_SEC = 420.0
BRAINROT_MIN_GAP_SEC = 30.0
BRAINROT_MAX_GAP_SEC = 180.0
BRAINROT_ESCALATION_SEC = 60.0
BRAINROT_BASE_DODGEBALLS = 1
BRAINROT_MAX_DODGEBALLS = 12
BRAINROT_SFX_COST = 50
BRAINROT_EMPTY_DISCONNECT_DELAY_SEC = 2.0
BRAINROT_ALONE_SWEEP_INTERVAL_SEC = 30.0

DODGEBALL_FILE = "dodgeball.mp3"
PLANKTON_FILE = "plankton.mp3"
STEEL_PIPE_FILE = "steel_pipe.mp3"


def brainrot_asset_dir() -> Path:
    return (LOCAL_AUDIO_ROOT / BRAINROT_FOLDER).resolve()


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
    pending_plankton: int,
    pending_pipe: int,
) -> list[Path]:
    n = dodgeball_burst_count(elapsed_since_last_trigger_sec)
    seq: list[Path] = [dodgeball_path] * n
    seq.extend([plankton_path] * pending_plankton)
    seq.extend([steel_pipe_path] * pending_pipe)
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
    pending_plankton: int = 0
    pending_pipe: int = 0
    controller_message: Optional[nextcord.Message] = None
    loop_task: Optional[asyncio.Task[None]] = None
    dodgeball_path: Path = field(default_factory=lambda: brainrot_asset_dir() / DODGEBALL_FILE)
    plankton_path: Path = field(default_factory=lambda: brainrot_asset_dir() / PLANKTON_FILE)
    steel_pipe_path: Path = field(default_factory=lambda: brainrot_asset_dir() / STEEL_PIPE_FILE)


class BrainrotControlView(nextcord.ui.View):
    def __init__(self, cog: BrainrotCog, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

        plankton_btn = nextcord.ui.Button(
            label=f"Buy plankton ({BRAINROT_SFX_COST})",
            style=nextcord.ButtonStyle.secondary,
            row=0,
        )

        async def plankton_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_buy_plankton(guild_id, interaction)

        plankton_btn.callback = plankton_cb

        pipe_btn = nextcord.ui.Button(
            label=f"Buy steel pipe ({BRAINROT_SFX_COST})",
            style=nextcord.ButtonStyle.secondary,
            row=0,
        )

        async def pipe_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_buy_pipe(guild_id, interaction)

        pipe_btn.callback = pipe_cb

        stop_btn = nextcord.ui.Button(label="Stop", style=nextcord.ButtonStyle.danger, row=1)

        async def stop_cb(interaction: nextcord.Interaction) -> None:
            await cog.handle_stop_button(guild_id, interaction)

        stop_btn.callback = stop_cb

        self.add_item(plankton_btn)
        self.add_item(pipe_btn)
        self.add_item(stop_btn)


class BrainrotCog(commands.Cog):
    """Brainrot voice SFX scheduler."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sessions: dict[int, BrainrotSession] = {}
        self._empty_disconnect_tasks: dict[int, asyncio.Task[None]] = {}
        self._alone_sweep_task: Optional[asyncio.Task[None]] = None

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
        deadline = (
            sess.last_trigger_mono + BRAINROT_MAX_SILENCE_SEC if sess else time.monotonic() + BRAINROT_MAX_SILENCE_SEC
        )
        remaining_force = max(0.0, deadline - time.monotonic())
        force_min = int(remaining_force // 60)
        force_sec = int(remaining_force % 60)
        pend_p = sess.pending_plankton if sess else 0
        pend_sp = sess.pending_pipe if sess else 0
        body = (
            "Silence… possibly interrupted.\n\n"
            f"**Forced burst within:** ~{force_min}m {force_sec}s\n"
            f"**Pending extras:** plankton ×{pend_p}, steel pipe ×{pend_sp}\n"
            "Purchases apply to the **next** burst (50 coins each)."
        )
        embed = nextcord.Embed(title="Brainrot", description=body, color=nextcord.Color.dark_grey())
        embed.set_footer(text="Native voice SFX — mutually exclusive with /music")
        return embed

    async def refresh_controller(self, guild_id: int) -> None:
        sess = self._sessions.get(guild_id)
        guild = self.bot.get_guild(guild_id)
        if sess is None or guild is None or sess.controller_message is None:
            return
        vc = guild.voice_client
        if vc is None or isinstance(vc, wavelink.Player) or not vc.is_connected():
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
        await interaction.followup.send("Added plankton to the next burst.", ephemeral=True)
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
        await interaction.followup.send("Added steel pipe to the next burst.", ephemeral=True)
        await self.refresh_controller(guild_id)

    async def handle_stop_button(self, guild_id: int, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if guild_id not in self._sessions:
            await interaction.followup.send("Nothing to stop.", ephemeral=True)
            return
        await self._full_stop(guild_id, disconnect_voice=True)
        await interaction.followup.send("Brainrot stopped.", ephemeral=True)

    async def _play_one_clip(self, vc: nextcord.VoiceClient, path: Path) -> None:
        source = nextcord.FFmpegOpusAudio(str(path))
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Optional[Exception]] = loop.create_future()

        def after_play(err: Optional[Exception]) -> None:
            if not fut.done():
                fut.set_result(err)

        vc.play(source, after=after_play)
        err = await fut
        if err:
            raise RuntimeError(str(err))

    async def _scheduler_loop(self, guild_id: int) -> None:
        try:
            while guild_id in self._sessions:
                sess = self._sessions[guild_id]
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    await self._full_stop(guild_id, disconnect_voice=False)
                    return
                vc = guild.voice_client
                if vc is None or isinstance(vc, wavelink.Player) or not vc.is_connected():
                    await self._full_stop(guild_id, disconnect_voice=False)
                    return

                now = time.monotonic()
                deadline = sess.last_trigger_mono + BRAINROT_MAX_SILENCE_SEC
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
                vc = guild.voice_client
                if vc is None or isinstance(vc, wavelink.Player) or not vc.is_connected():
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
                    pending_plankton=sess.pending_plankton,
                    pending_pipe=sess.pending_pipe,
                )
                sess.pending_plankton = 0
                sess.pending_pipe = 0

                try:
                    for p in burst:
                        if guild_id not in self._sessions:
                            return
                        guild = self.bot.get_guild(guild_id)
                        if guild is None:
                            await self._full_stop(guild_id, disconnect_voice=False)
                            return
                        vc = guild.voice_client
                        if vc is None or isinstance(vc, wavelink.Player):
                            await self._full_stop(guild_id, disconnect_voice=False)
                            return
                        await self._play_one_clip(vc, p)
                except Exception as e:
                    _LOG.warning("brainrot burst playback guild=%s: %s", guild_id, e)

                sess.last_trigger_mono = time.monotonic()
                await self.refresh_controller(guild_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("brainrot scheduler guild=%s", guild_id)
            if guild_id in self._sessions:
                await self._full_stop(guild_id, disconnect_voice=True)

    async def _cleanup_session_record(self, guild_id: int, *, disconnect_voice: bool) -> None:
        """Remove session metadata and optionally disconnect native voice (not Lavalink Player)."""
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
                vc = guild.voice_client
                if vc is not None and not isinstance(vc, wavelink.Player):
                    try:
                        await vc.disconnect(force=True)
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

        asset_root = brainrot_asset_dir()
        dodge_path = asset_root / DODGEBALL_FILE
        plank_path = asset_root / PLANKTON_FILE
        pipe_path = asset_root / STEEL_PIPE_FILE

        if not dodge_path.is_file():
            await self._slash_reply(
                interaction,
                f"Missing `{_path_display(dodge_path)}`. Add dodgeball.mp3 under local_audio/brainrot.",
            )
            return

        rng = random.Random(seed) if seed is not None else random.Random()

        try:
            vc = await voice_channel.connect(timeout=30.0, reconnect=True)
        except Exception as e:
            await self._slash_reply(interaction, f"Could not connect to voice: {e}")
            return

        if isinstance(vc, wavelink.Player):
            await self._slash_reply(interaction, "Voice conflict with Lavalink player.")
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            return

        mono = time.monotonic()
        sess = BrainrotSession(
            rng=rng,
            voice_channel_id=voice_channel.id,
            last_trigger_mono=mono,
            dodgeball_path=dodge_path,
            plankton_path=plank_path,
            steel_pipe_path=pipe_path,
        )
        self._sessions[guild.id] = sess

        embed = self._embed_for_session(guild.id)
        view = BrainrotControlView(self, guild.id)
        try:
            msg = await voice_channel.send(embed=embed, view=view)
            sess.controller_message = msg
        except Exception as e:
            self._sessions.pop(guild.id, None)
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
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
    cog = BrainrotCog(bot)
    bot.add_cog(cog)
    cog._alone_sweep_task = asyncio.get_running_loop().create_task(cog._alone_in_voice_sweep_loop())


def teardown(bot: commands.Bot) -> None:
    cog = bot.get_cog("BrainrotCog")
    if isinstance(cog, BrainrotCog) and cog._alone_sweep_task and not cog._alone_sweep_task.done():
        cog._alone_sweep_task.cancel()
