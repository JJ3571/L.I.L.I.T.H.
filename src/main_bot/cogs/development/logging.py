"""Prefix command `.logging` for admins to view recent bot logs with a refresh button."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional, Set, Tuple

import nextcord
from nextcord.ext import commands

from main_bot.paths import PROJECT_ROOT
from main_bot.server_configs.config import BOT_LOG_FILE, BOT_LOG_JOURNAL_UNIT, admin_user_ids

LOG_LINE_COUNT = 12
MAX_EMBED_BODY = 3800


def _default_log_path() -> Path:
    if BOT_LOG_FILE.strip():
        return Path(BOT_LOG_FILE).expanduser()
    return PROJECT_ROOT / "nextcord.log"


def _tail_file(path: Path, max_lines: int) -> Tuple[str, str]:
    """Return (snippet, source_label)."""
    label = f"file `{path}`"
    try:
        if not path.is_file():
            return f"(no file at {path})", label
    except OSError as e:
        return f"(error accessing path: {e})", label

    chunk_size = 8192
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return "(empty)", label
            data = b""
            pos = size
            while pos > 0 and data.count(b"\n") <= max_lines + 1:
                read_len = min(chunk_size, pos)
                pos -= read_len
                f.seek(pos)
                data = f.read(read_len) + data
        lines = data.splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        text = "\n".join(line.decode("utf-8", errors="replace") for line in tail)
        return (text if text else "(empty)", label)
    except OSError as e:
        return f"(read error: {e})", label


async def _tail_journal(unit: str, max_lines: int) -> Optional[str]:
    if not unit.strip():
        return None
    if not shutil.which("journalctl"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl",
            f"-u{unit.strip()}",
            "-n",
            str(max_lines),
            "--no-pager",
            "-o",
            "short-iso",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            msg = err.decode("utf-8", errors="replace").strip() or out.decode("utf-8", errors="replace")
            return f"(journalctl failed: {msg})"
        text = out.decode("utf-8", errors="replace").strip()
        return text if text else "(no journal entries)"
    except OSError as e:
        return f"(journalctl error: {e})"


def _truncate_block(text: str) -> str:
    if len(text) <= MAX_EMBED_BODY:
        return text
    return text[: MAX_EMBED_BODY - 24] + "\n… (truncated)"


async def fetch_log_snippet() -> Tuple[str, str]:
    """
    Returns (body_text, source description for embed footer).
    Prefer journal when BOT_LOG_JOURNAL_UNIT is set; fall back to log file.
    """
    if BOT_LOG_JOURNAL_UNIT.strip():
        journal_text = await _tail_journal(BOT_LOG_JOURNAL_UNIT, LOG_LINE_COUNT)
        if journal_text is not None:
            return _truncate_block(journal_text), f"journalctl -u {BOT_LOG_JOURNAL_UNIT.strip()}"
    path = _default_log_path()
    body, label = _tail_file(path, LOG_LINE_COUNT)
    return _truncate_block(body), label


def _make_embed(body: str, source: str, requester: nextcord.abc.User) -> nextcord.Embed:
    embed = nextcord.Embed(
        title="Bot logs",
        description=f"Last ~{LOG_LINE_COUNT} lines.\n```\n{body}\n```",
        color=nextcord.Color.dark_teal(),
    )
    embed.set_footer(text=f"Source: {source} · requested by {requester}")
    return embed


class LogRefreshView(nextcord.ui.View):
    def __init__(self, admin_ids: Set[int]):
        super().__init__(timeout=600.0)
        self._admin_ids = admin_ids

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self._admin_ids

    @nextcord.ui.button(label="Refresh", style=nextcord.ButtonStyle.primary, emoji="🔄")
    async def refresh_logs(self, button: nextcord.ui.Button, interaction: nextcord.Interaction) -> None:
        if not self._is_admin(interaction.user.id):
            await interaction.response.send_message("You do not have permission to refresh this.", ephemeral=True)
            return
        await interaction.response.defer()
        body, source = await fetch_log_snippet()
        embed = _make_embed(body, source, interaction.user)
        await interaction.edit_original_response(embed=embed, view=self)


class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="logging")
    async def logging_cmd(self, ctx: commands.Context) -> None:
        if ctx.author.id not in admin_user_ids:
            await ctx.send("You do not have permission to use this command.")
            return

        body, source = await fetch_log_snippet()
        embed = _make_embed(body, source, ctx.author)
        view = LogRefreshView(admin_ids=set(admin_user_ids))
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    bot.add_cog(LoggingCog(bot))
