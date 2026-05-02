"""Prefix command `.logging` for admins to view recent bot logs with controls."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import nextcord
from nextcord.ext import commands

from main_bot.paths import PROJECT_ROOT
from main_bot.server_configs.config import (
    BOT_LOG_FILE,
    BOT_LOG_JOURNAL_EXTRA_UNITS,
    BOT_LOG_JOURNAL_UNIT,
    admin_user_ids,
)

LINES_PER_PAGE = 6
PAGE_COUNT = 5  # pages 0..4 — newest first, four older pages
BUFFER_LINE_COUNT = LINES_PER_PAGE * PAGE_COUNT
MAX_EMBED_BODY = 3800
MAX_BUTTON_LABEL = 80


def _default_log_path() -> Path:
    if BOT_LOG_FILE.strip():
        return Path(BOT_LOG_FILE).expanduser()
    return PROJECT_ROOT / "nextcord.log"


def _tail_file_lines(path: Path, max_lines: int) -> Tuple[List[str], str]:
    """Return (lines newest-last, source_label)."""
    label = f"file `{path}`"
    try:
        if not path.is_file():
            return [f"(no file at {path})"], label
    except OSError as e:
        return [f"(error accessing path: {e})"], label

    chunk_size = 8192
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return ["(empty)"], label
            data = b""
            pos = size
            while pos > 0 and data.count(b"\n") <= max_lines + 1:
                read_len = min(chunk_size, pos)
                pos -= read_len
                f.seek(pos)
                data = f.read(read_len) + data
        raw_lines = data.splitlines()
        tail = raw_lines[-max_lines:] if len(raw_lines) > max_lines else raw_lines
        text_lines = [line.decode("utf-8", errors="replace") for line in tail]
        return (text_lines if text_lines else ["(empty)"], label)
    except OSError as e:
        return [f"(read error: {e})"], label


async def _tail_journal_lines(unit: str, max_lines: int) -> Optional[Tuple[List[str], str]]:
    if not unit.strip():
        return None
    if not shutil.which("journalctl"):
        return None
    label = f"journalctl -u {unit.strip()}"
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
            return [f"(journalctl failed: {msg})"], label
        text = out.decode("utf-8", errors="replace").strip()
        if not text:
            return ["(no journal entries)"], label
        lines = text.splitlines()
        return (lines if lines else ["(no journal entries)"], label)
    except OSError as e:
        return [f"(journalctl error: {e})"], label


def _extra_journal_unit_names() -> List[str]:
    primary = BOT_LOG_JOURNAL_UNIT.strip()
    seen: Set[str] = set()
    out: List[str] = []
    for part in BOT_LOG_JOURNAL_EXTRA_UNITS.split(","):
        u = part.strip()
        if not u or u in seen:
            continue
        if primary and u == primary:
            continue
        seen.add(u)
        out.append(u)
    return out


def _display_title_for_source(source_id: str) -> str:
    if source_id == "__file__":
        return "Bot logs"
    stem = source_id.removesuffix(".service").replace("_", " ").strip()
    return f"{stem.title()} logs" if stem else f"{source_id} logs"


def _short_button_label(source_id: str) -> str:
    if source_id == "__file__":
        path = _default_log_path()
        name = path.name or str(path)
        raw = f"Log file ({name})" if name else "Log file"
    else:
        raw = source_id.removesuffix(".service").replace("_", " ").strip() or source_id
    if len(raw) > MAX_BUTTON_LABEL:
        return raw[: MAX_BUTTON_LABEL - 1] + "…"
    return raw


def _configured_sources() -> List[Tuple[str, str]]:
    """(source_id, button label) in UI order."""
    out: List[Tuple[str, str]] = []
    primary = BOT_LOG_JOURNAL_UNIT.strip()
    if primary:
        out.append((primary, _short_button_label(primary)))
    else:
        out.append(("__file__", _short_button_label("__file__")))
    for u in _extra_journal_unit_names():
        out.append((u, _short_button_label(u)))
    return out


def _truncate_block(text: str) -> str:
    if len(text) <= MAX_EMBED_BODY:
        return text
    return text[: MAX_EMBED_BODY - 24] + "\n… (truncated)"


def _slice_page(lines: List[str], page: int) -> List[str]:
    """Page 0 is the newest `LINES_PER_PAGE` lines of the buffered tail."""
    if not lines or page < 0:
        return []
    n = len(lines)
    end = n - page * LINES_PER_PAGE
    start = max(0, end - LINES_PER_PAGE)
    if end <= 0:
        return []
    return lines[start:end]


def _max_page_index(lines: List[str]) -> int:
    if not lines:
        return 0
    return (len(lines) - 1) // LINES_PER_PAGE


async def _fetch_source_lines(source_id: str) -> Tuple[List[str], str]:
    if source_id == "__file__":
        path = _default_log_path()
        return _tail_file_lines(path, BUFFER_LINE_COUNT)
    got = await _tail_journal_lines(source_id, BUFFER_LINE_COUNT)
    if got is None:
        return (
            ["(journalctl not available; cannot read this unit on this host)"],
            f"journalctl -u {source_id.strip()}",
        )
    return got


async def _fetch_all_sources(
    sources: List[Tuple[str, str]],
) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    ids = [s[0] for s in sources]
    results = await asyncio.gather(*[_fetch_source_lines(sid) for sid in ids])
    cache = {sid: lines for sid, (lines, _) in zip(ids, results)}
    footers = {sid: foot for sid, (_, foot) in zip(ids, results)}
    return cache, footers


def _build_embed(
    requester: nextcord.abc.User,
    source_id: str,
    page: int,
    lines: List[str],
    footer_source: str,
) -> nextcord.Embed:
    max_pi = _max_page_index(lines)
    page = max(0, min(page, max_pi))
    chunk = _slice_page(lines, page)
    body = _truncate_block("\n".join(chunk) if chunk else "(empty)")
    page_human = page + 1
    pages_total = max_pi + 1
    title = _display_title_for_source(source_id)
    desc = (
        f"Page **{page_human}** / **{pages_total}** · **{LINES_PER_PAGE}** lines per page "
        f"· buffer **{BUFFER_LINE_COUNT}** newest lines\n```\n{body}\n```"
    )
    embed = nextcord.Embed(title=title, description=desc, color=nextcord.Color.dark_teal())
    embed.set_footer(text=f"Source: {footer_source} · requested by {requester}")
    return embed


class LoggingControlView(nextcord.ui.View):
    def __init__(
        self,
        admin_ids: Set[int],
        user_command_message: Optional[nextcord.Message],
        sources: List[Tuple[str, str]],
        current_source: str,
        page: int,
        cache: Dict[str, List[str]],
        footers: Dict[str, str],
    ):
        super().__init__(timeout=600.0)
        self._admin_ids = admin_ids
        self._user_command_message = user_command_message
        self._sources = sources
        self._current_source = current_source
        self._page = page
        self._cache = cache
        self._footers = footers
        self._build_items()

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self._admin_ids

    def _build_items(self) -> None:
        lines = self._cache.get(self._current_source, [])
        max_pi = _max_page_index(lines)

        refresh = nextcord.ui.Button(label="Refresh", style=nextcord.ButtonStyle.primary, emoji="🔄")

        async def refresh_cb(interaction: nextcord.Interaction) -> None:
            if not self._is_admin(interaction.user.id):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            await interaction.response.defer()
            cache, footers = await _fetch_all_sources(self._sources)
            nv = LoggingControlView(
                self._admin_ids,
                self._user_command_message,
                self._sources,
                self._current_source,
                0,
                cache,
                footers,
            )
            embed = _build_embed(
                interaction.user,
                nv._current_source,
                0,
                nv._cache.get(nv._current_source, []),
                nv._footers.get(nv._current_source, ""),
            )
            await interaction.edit_original_message(embed=embed, view=nv)

        refresh.callback = refresh_cb
        self.add_item(refresh)

        delete_btn = nextcord.ui.Button(label="Delete", style=nextcord.ButtonStyle.danger, emoji="🗑️")

        async def delete_cb(interaction: nextcord.Interaction) -> None:
            if not self._is_admin(interaction.user.id):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            self.stop()
            try:
                await interaction.message.delete()
            except (nextcord.NotFound, nextcord.Forbidden, nextcord.HTTPException):
                pass
            if self._user_command_message:
                try:
                    await self._user_command_message.delete()
                except (nextcord.NotFound, nextcord.Forbidden, nextcord.HTTPException):
                    pass

        delete_btn.callback = delete_cb
        self.add_item(delete_btn)

        prev_b = nextcord.ui.Button(label="Older", style=nextcord.ButtonStyle.secondary, emoji="◀")
        prev_b.disabled = self._page >= max_pi
        next_b = nextcord.ui.Button(label="Newer", style=nextcord.ButtonStyle.secondary, emoji="▶")
        next_b.disabled = self._page <= 0

        async def prev_cb(interaction: nextcord.Interaction) -> None:
            if not self._is_admin(interaction.user.id):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            lines = self._cache.get(self._current_source, [])
            max_p = _max_page_index(lines)
            new_page = min(self._page + 1, max_p)
            nv = LoggingControlView(
                self._admin_ids,
                self._user_command_message,
                self._sources,
                self._current_source,
                new_page,
                dict(self._cache),
                dict(self._footers),
            )
            embed = _build_embed(
                interaction.user,
                nv._current_source,
                new_page,
                nv._cache.get(nv._current_source, []),
                nv._footers.get(nv._current_source, ""),
            )
            await interaction.response.edit_message(embed=embed, view=nv)

        async def next_cb(interaction: nextcord.Interaction) -> None:
            if not self._is_admin(interaction.user.id):
                await interaction.response.send_message("You do not have permission.", ephemeral=True)
                return
            new_page = max(self._page - 1, 0)
            nv = LoggingControlView(
                self._admin_ids,
                self._user_command_message,
                self._sources,
                self._current_source,
                new_page,
                dict(self._cache),
                dict(self._footers),
            )
            embed = _build_embed(
                interaction.user,
                nv._current_source,
                new_page,
                nv._cache.get(nv._current_source, []),
                nv._footers.get(nv._current_source, ""),
            )
            await interaction.response.edit_message(embed=embed, view=nv)

        prev_b.callback = prev_cb
        next_b.callback = next_cb
        self.add_item(prev_b)
        self.add_item(next_b)

        if len(self._sources) > 1:
            for source_id, label in self._sources:
                style = (
                    nextcord.ButtonStyle.primary
                    if source_id == self._current_source
                    else nextcord.ButtonStyle.secondary
                )
                btn = nextcord.ui.Button(label=label, style=style)

                async def svc_cb(interaction: nextcord.Interaction, sid: str = source_id) -> None:
                    if not self._is_admin(interaction.user.id):
                        await interaction.response.send_message("You do not have permission.", ephemeral=True)
                        return
                    lines = self._cache.get(sid, [])
                    nv = LoggingControlView(
                        self._admin_ids,
                        self._user_command_message,
                        self._sources,
                        sid,
                        0,
                        dict(self._cache),
                        dict(self._footers),
                    )
                    embed = _build_embed(
                        interaction.user,
                        sid,
                        0,
                        lines,
                        nv._footers.get(sid, ""),
                    )
                    await interaction.response.edit_message(embed=embed, view=nv)

                btn.callback = svc_cb
                self.add_item(btn)


class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="logging")
    async def logging_cmd(self, ctx: commands.Context) -> None:
        if ctx.author.id not in admin_user_ids:
            await ctx.send("You do not have permission to use this command.")
            return

        sources = _configured_sources()
        cache, footers = await _fetch_all_sources(sources)
        current = sources[0][0]
        view = LoggingControlView(
            admin_ids=set(admin_user_ids),
            user_command_message=ctx.message,
            sources=sources,
            current_source=current,
            page=0,
            cache=cache,
            footers=footers,
        )
        embed = _build_embed(ctx.author, current, 0, cache.get(current, []), footers.get(current, ""))
        await ctx.send(embed=embed, view=view)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(LoggingCog(bot))
