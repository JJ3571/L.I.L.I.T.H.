import json
import os
import re
import socket
import ast
from typing import Any, Dict, List, NamedTuple, Tuple


def _get_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default

    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("\"", "'"):
        v = v[1:-1].strip()

    return v


def _strip_hash_comments_outside_strings(text: str) -> str:
    """
    Allow Doppler values like JSON but with '# comments' on their own lines or after items.
    Strips '#' comments only when outside of quoted strings.
    """
    out_chars: List[str] = []
    in_string = False
    quote_char = ""
    escape = False

    i = 0
    while i < len(text):
        ch = text[i]

        if in_string:
            out_chars.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
                quote_char = ""
            i += 1
            continue

        if ch in ("\"", "'"):
            in_string = True
            quote_char = ch
            out_chars.append(ch)
            i += 1
            continue

        if ch == "#":
            # Skip until end of line / record end. Also stop at `]` or `}` so inline
            # `# label` after a number does not swallow the closing bracket (e.g. `[1 #ch]`).
            while i < len(text) and text[i] not in ("\n", "\r", "]", "}"):
                i += 1
            continue

        out_chars.append(ch)
        i += 1

    return "".join(out_chars)


def _relax_json_syntax(text: str) -> str:
    """
    Make JSON parsing more tolerant:
    - removes trailing commas before ']' or '}'
    """
    # Remove trailing commas like ", ]" or ",\n}"
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _get_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    value = value.strip()
    if value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_json(name: str, default: Any) -> Any:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default

    cleaned = _relax_json_syntax(_strip_hash_comments_outside_strings(value)).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback for python-ish literals (single quotes, etc.) after stripping comments.
        try:
            return ast.literal_eval(cleaned)
        except (ValueError, SyntaxError):
            return default


def _get_json_int_list(name: str) -> List[int]:
    raw = _get_json(name, [])
    if not isinstance(raw, list):
        # If someone provided a non-JSON list-like string, fallback to extracting digits.
        if isinstance(raw, str):
            return [int(x) for x in re.findall(r"\d+", raw)]
        return []
    out: List[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _get_json_dict(name: str) -> Dict[str, Any]:
    raw = _get_json(name, {})
    return raw if isinstance(raw, dict) else {}


def _get_json_str_list(name: str) -> List[str]:
    raw = _get_json(name, [])
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    v = value.strip().lower()
    if v == "":
        return default
    return v in ("1", "true", "yes", "on")


class MusicFolderEnvSlot(NamedTuple):
    """One configured local-music folder: slash name / HTTP segment equals ``folder``."""

    folder: str
    shuffle_random_start: bool


# Discord chat-input command names (same rule as tests/test_production_cogs.py).
_DISCORD_APP_COMMAND_NAME_RE = re.compile(r"^[-_a-z0-9]{1,32}$", re.ASCII)
_RESERVED_MUSIC_FOLDER_ENV_NAMES = frozenset({"gaming", "brainrot"})
_MUSIC_FOLDER_SLOT_COUNT = 25


def _load_music_folder_env_slots() -> Tuple[MusicFolderEnvSlot, ...]:
    """Parse ``MUSIC_FOLDER_1``…``MUSIC_FOLDER_25`` and matching ``MUSIC_n_SHUFFLE_START`` flags."""
    seen_cf: set[str] = set()
    out: List[MusicFolderEnvSlot] = []
    for n in range(1, _MUSIC_FOLDER_SLOT_COUNT + 1):
        raw = _get_str(f"MUSIC_FOLDER_{n}", "")
        if not raw:
            continue
        folder = raw.strip()
        if folder.casefold() in {x.casefold() for x in _RESERVED_MUSIC_FOLDER_ENV_NAMES}:
            print(
                f"[CONFIG] MUSIC_FOLDER_{n}={folder!r} is reserved (gaming/brainrot); skipping this slot.",
            )
            continue
        if not _DISCORD_APP_COMMAND_NAME_RE.match(folder):
            print(
                f"[CONFIG] MUSIC_FOLDER_{n}={folder!r} must match Discord slash name rules "
                r"^[-_a-z0-9]{1,32}$; skipping.",
            )
            continue
        cf = folder.casefold()
        if cf in seen_cf:
            print(f"[CONFIG] Duplicate MUSIC_FOLDER_* name {folder!r} (case-insensitive); skipping slot {n}.")
            continue
        seen_cf.add(cf)
        shuffle_start = _get_bool(f"MUSIC_{n}_SHUFFLE_START", False)
        out.append(MusicFolderEnvSlot(folder, shuffle_start))
    return tuple(out)


# -------- Core bot config (Doppler env vars) --------

DISCORD_BOT_TOKEN = _get_str("DISCORD_BOT_TOKEN", "")
GUILD_ID = _get_int("GUILD_ID", 0)

# Lavalink (music cog via Wavelink). Lavalink v4 expected — align credentials with ``application.yml`` server.password.
LAVALINK_URI = _get_str("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = _get_str("LAVALINK_PASSWORD", "youshallnotpass")

# HTTP used to expose ``local_audio/music/{folder}`` (jazz, lofi, gaming) to Lavalink (see ``jazz_http_server``).
# HOST is embedded in Lavalink-facing URLs; BIND_HOST is aiohttp bind (empty/unset ⇒ same as HOST).
MUSIC_LOCAL_HTTP_HOST = _get_str("MUSIC_LOCAL_HTTP_HOST", "127.0.0.1")
MUSIC_LOCAL_HTTP_BIND_HOST = _get_str("MUSIC_LOCAL_HTTP_BIND_HOST", "")
MUSIC_LOCAL_HTTP_PORT = _get_int("MUSIC_LOCAL_HTTP_PORT", 8765)
# Lavalink/Wavelink player volume on voice join: 100 = 100% (library default), 50 = 50%, up to 1000 for boost.
MUSIC_DEFAULT_PLAYER_VOLUME = max(0, min(_get_int("MUSIC_DEFAULT_PLAYER_VOLUME", 50), 1000))
# Optional flat folders under ``local_audio/music/{name}`` exposed as /name slash commands (see music cog).
MUSIC_CONFIGURED_FOLDER_SLOTS: Tuple[MusicFolderEnvSlot, ...] = _load_music_folder_env_slots()
APPLICATION_ID = _get_int("APPLICATION_ID", 0)
OPENCODE_API_KEY = _get_str("OPENCODE_API_KEY", "")
OPENCODE_MODEL = _get_str("OPENCODE_MODEL", "glm-5.3-flash")
ENVIRONMENT = _get_str("ENVIRONMENT", "")


# -------- Environment Detection (kept) --------

def get_local_ip() -> str:
    """Get the local IP address to determine environment."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"


def is_development_environment() -> bool:
    """Detect if we're running in development (local network) or production (VPS)."""
    env = (ENVIRONMENT or "").strip().lower()
    if env in {"production", "prod"}:
        return False
    if env in {"development", "dev"}:
        return True

    local_ip = get_local_ip()
    if local_ip.startswith("192.168.") or local_ip.startswith("10."):
        return True

    return True


# -------- Crafty Controller (values come from env) --------

IS_DEVELOPMENT = is_development_environment()

CRAFTY_BASE_URL = _get_str("CRAFTY_BASE_URL", "")
CRAFTY_USERNAME = _get_str("CRAFTY_USERNAME", "")
CRAFTY_PASSWORD = _get_str("CRAFTY_PASSWORD", "")

if IS_DEVELOPMENT:
    print("[CONFIG] Development environment detected")
else:
    print("[CONFIG] Production environment detected")

if not DISCORD_BOT_TOKEN:
    print("[CONFIG] DISCORD_BOT_TOKEN is empty/missing (Doppler may not be injecting env vars).")


# -------- Cog/shared config (secrets + infra; guild snowflakes live in guild_settings / .setup) --------

# API keys
OMDB_API_KEY = _get_str("OMDB_API_KEY", "")
OMDB_API_URL = _get_str("OMDB_API_URL", "")
BRAVE_SEARCH_API_KEY = _get_str("BRAVE_SEARCH_API_KEY", "")
SERPENT_API_KEY = _get_str("SERPENT_API_KEY", "")
# Tier list images: ``serpent`` (Google via apiserpent.com) or ``brave``. Auto-picks Serpent when its key is set.
TIERLIST_IMAGE_ENGINE = _get_str("TIERLIST_IMAGE_ENGINE", "").lower()
# Serpent image engine param: google, bing, yahoo, ddg (default google).
SERPENT_IMAGE_ENGINE = _get_str("SERPENT_IMAGE_ENGINE", "google")

# TCG display (JSON) — stays in env for v1 (poor modal fit)
MANA_SYMBOLS = _get_json_dict("MANA_SYMBOLS")

# Say config (JSON + webhook secret) — avatars/webhook stay in env for v1
webhook_url = _get_str("WEBHOOK_URL", "")
character_avatars = _get_json_dict("CHARACTER_AVATARS")

# Bot log viewer (.logging): optional systemd unit on Linux (e.g. discord_bot); else tails ``BOT_LOG_FILE``.
# When ``BOT_LOG_FILE`` is unset, logs go to ``<project>/logs/discord_bot.log`` (see ``main_bot.paths.runtime_bot_log_path``).
# BOT_LOG_JOURNAL_EXTRA_UNITS: comma-separated units for additional panes (e.g. lavalink.service).
BOT_LOG_JOURNAL_UNIT = _get_str("BOT_LOG_JOURNAL_UNIT", "")
BOT_LOG_JOURNAL_EXTRA_UNITS = _get_str("BOT_LOG_JOURNAL_EXTRA_UNITS", "")
BOT_LOG_FILE = _get_str("BOT_LOG_FILE", "")
