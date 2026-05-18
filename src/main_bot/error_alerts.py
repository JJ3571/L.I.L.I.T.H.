"""Send ERROR-level logs and unhandled bot exceptions to Discord (ping + embed).

Configure ``ERROR_ALERT_USER_ID`` and/or ``ERROR_ALERT_CHANNEL_ID`` in
``server_configs/config`` (via env). If both are ``0``, alerting is disabled.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
import weakref
from typing import Any, Optional

import nextcord
from nextcord.errors import ApplicationCheckFailure, ApplicationInvokeError
from nextcord.ext import commands

from main_bot.server_configs.config import ERROR_ALERT_CHANNEL_ID, ERROR_ALERT_USER_ID

_LOG = logging.getLogger(__name__)

_MAX_EMBED_DESC = 3900
_MIN_INTERVAL_SEC = 1.5
_ALERT_LOGGER_PREFIX = "main_bot.error_alerts"


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n… (truncated)"


def _format_exc(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def _format_log_record(record: logging.LogRecord) -> str:
    lines = [record.getMessage()]
    if record.exc_info and record.exc_info[1] is not None:
        lines.append(_format_exc(record.exc_info[1]))
    return "\n".join(lines).strip()


def _is_unknown_interaction_error(exc: BaseException) -> bool:
    """Discord returns 10062 when the interaction token expired or was already used."""
    cur: BaseException | None = exc
    while cur is not None:
        if getattr(cur, "code", None) == 10062:
            return True
        if isinstance(cur, ApplicationInvokeError) and cur.original is not None:
            cur = cur.original
            continue
        cur = cur.__cause__
    return False


class _DiscordLogHandler(logging.Handler):
    """Forwards ERROR+ log records to the bot loop (non-blocking)."""

    def __init__(self, bot_ref: weakref.ReferenceType[commands.Bot]) -> None:
        super().__init__(level=logging.ERROR)
        self._bot_ref = bot_ref
        self._last_emit = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_ALERT_LOGGER_PREFIX):
            return
        bot = self._bot_ref()
        if bot is None:
            return
        loop = getattr(bot, "loop", None)
        if loop is None or not loop.is_running():
            return
        import time

        now = time.monotonic()
        if now - self._last_emit < _MIN_INTERVAL_SEC:
            return
        self._last_emit = now

        summary = f"Log: {record.name}"
        detail = _format_log_record(record)
        try:
            asyncio.run_coroutine_threadsafe(_send_alert(bot, summary=summary, detail=detail), loop)
        except RuntimeError:
            pass


def install_error_alerts(bot: commands.Bot) -> None:
    if getattr(bot, "_error_alerts_installed", False):
        return
    bot._error_alerts_installed = True  # type: ignore[attr-defined]

    bot_ref = weakref.ref(bot)

    async def on_error(event_method: str, *args: Any, **kwargs: Any) -> None:
        detail = traceback.format_exc()
        print(f"Ignoring exception in {event_method}", file=sys.stderr, flush=True)
        print(detail, file=sys.stderr, end="", flush=True)
        await _send_alert(
            bot,
            summary=f"Event error: {event_method}",
            detail=detail.strip() or "(no traceback — check stderr)",
        )

    async def on_application_command_error(
        interaction: nextcord.Interaction,
        exception: BaseException,
    ) -> None:
        if interaction.application_command and interaction.application_command.has_error_handler():
            return

        if isinstance(exception, ApplicationCheckFailure):
            return

        if _is_unknown_interaction_error(exception):
            _LOG.debug("Skipping alert: unknown / expired interaction (10062)", exc_info=exception)
            return

        print(f"Ignoring exception in command {interaction.application_command}:", file=sys.stderr)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stderr
        )
        detail = _format_exc(exception)
        name = getattr(interaction.application_command, "name", None) or "unknown"
        await _send_alert(
            bot,
            summary=f"Slash / app command: {name}",
            detail=detail,
        )

    async def on_command_error(ctx: commands.Context, exception: commands.CommandError) -> None:
        command = ctx.command
        if command and command.has_error_handler():
            return
        cog = ctx.cog
        if cog and cog.has_error_handler():
            return

        noise = (
            commands.CommandNotFound,
            commands.CheckFailure,
            commands.MissingRequiredArgument,
            commands.BadArgument,
            commands.MissingPermissions,
            commands.MissingRole,
            commands.BotMissingPermissions,
            commands.CommandOnCooldown,
            commands.DisabledCommand,
            commands.MaxConcurrencyReached,
            commands.NoPrivateMessage,
        )
        if isinstance(exception, noise):
            return

        print(f"Ignoring exception in command {ctx.command}:", file=sys.stderr)
        traceback.print_exception(
            type(exception), exception, exception.__traceback__, file=sys.stderr
        )
        cmd = ctx.command.qualified_name if ctx.command else ctx.invoked_with or "unknown"
        await _send_alert(
            bot,
            summary=f"Prefix command: {cmd}",
            detail=_format_exc(exception),
        )

    setattr(bot, "on_error", on_error)
    setattr(bot, "on_application_command_error", on_application_command_error)
    setattr(bot, "on_command_error", on_command_error)

    handler = _DiscordLogHandler(bot_ref)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


async def ensure_asyncio_exception_handler(bot: commands.Bot) -> None:
    """Call once from ``on_ready`` (after the client loop is running)."""
    if getattr(bot, "_asyncio_exc_handler_installed", False):
        return
    bot._asyncio_exc_handler_installed = True  # type: ignore[attr-defined]
    bot_ref = weakref.ref(bot)
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def _loop_handler(loop_: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if previous is not None:
            previous(loop_, context)
        else:
            loop_.default_exception_handler(context)
        b = bot_ref()
        if b is None:
            return
        if getattr(loop_, "is_closed", lambda: False)():
            return
        coro = _send_alert_from_asyncio_context(b, context)
        try:
            loop_.create_task(coro)
        except RuntimeError:
            # Shutdown: coroutine was built but cannot be scheduled; close it to
            # avoid "coroutine was never awaited" / RuntimeWarning.
            coro.close()

    loop.set_exception_handler(_loop_handler)


async def _send_alert_from_asyncio_context(bot: commands.Bot, context: dict[str, Any]) -> None:
    msg = context.get("message", "asyncio task exception")
    exc = context.get("exception")
    parts = [str(msg)]
    if exc is not None:
        parts.append(_format_exc(exc))
    detail = "\n\n".join(parts)
    await _send_alert(bot, summary="Asyncio task / callback failure", detail=detail)


async def _send_alert(bot: commands.Bot, *, summary: str, detail: str) -> None:
    if not ERROR_ALERT_USER_ID and not ERROR_ALERT_CHANNEL_ID:
        return
    if not bot.is_ready():
        return

    body = _truncate(detail, _MAX_EMBED_DESC)
    embed = nextcord.Embed(
        title=_truncate(summary, 256),
        description=f"```\n{body}\n```",
        color=nextcord.Color.dark_red(),
    )
    embed.set_footer(text="Bot error alert")

    content: Optional[str] = None
    mentions = nextcord.AllowedMentions.none()
    if ERROR_ALERT_USER_ID:
        content = f"<@{ERROR_ALERT_USER_ID}>"
        mentions = nextcord.AllowedMentions(users=[nextcord.Object(id=ERROR_ALERT_USER_ID)])

    try:
        if ERROR_ALERT_CHANNEL_ID:
            channel = bot.get_channel(ERROR_ALERT_CHANNEL_ID)
            if channel is None:
                channel = await bot.fetch_channel(ERROR_ALERT_CHANNEL_ID)
            if isinstance(channel, nextcord.abc.Messageable):
                await channel.send(content=content, embed=embed, allowed_mentions=mentions)
                return
        if ERROR_ALERT_USER_ID:
            user = await bot.fetch_user(ERROR_ALERT_USER_ID)
            await user.send(embed=embed)
    except nextcord.HTTPException as e:
        _LOG.warning("Could not deliver error alert to Discord: %s", e)
    except Exception:
        _LOG.debug("Could not deliver error alert to Discord", exc_info=True)
