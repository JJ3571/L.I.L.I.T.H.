import json
import os
import re
import socket
import ast
from typing import Any, Dict, FrozenSet, List


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
            # Skip until end of line
            while i < len(text) and text[i] not in ("\n", "\r"):
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


def _frozenset_lower(items: List[str]) -> FrozenSet[str]:
    return frozenset(s.casefold().strip() for s in items if s and s.strip())


# -------- Core bot config (Doppler env vars) --------

DISCORD_BOT_TOKEN = _get_str("DISCORD_BOT_TOKEN", "")
GUILD_ID = _get_int("GUILD_ID", 0)

# Lavalink (music cog via Wavelink). Lavalink v4 expected — align credentials with ``application.yml`` server.password.
LAVALINK_URI = _get_str("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = _get_str("LAVALINK_PASSWORD", "youshallnotpass")

# Loopback HTTP used to expose ``local_music/{folder}`` (jazz, lofi, minecraft) to Lavalink (see ``jazz_http_server``).
MUSIC_LOCAL_HTTP_HOST = _get_str("MUSIC_LOCAL_HTTP_HOST", "127.0.0.1")
MUSIC_LOCAL_HTTP_PORT = _get_int("MUSIC_LOCAL_HTTP_PORT", 8765)
# Voice channel IDs where slash music commands and VC controls are blocked (e.g. recording, watchparty). JSON array of ints; empty = disabled.
MUSIC_VOICE_CHANNEL_DENYLIST_IDS = frozenset(_get_json_int_list("MUSIC_VOICE_CHANNEL_DENYLIST"))
APPLICATION_ID = _get_int("APPLICATION_ID", 0)
GEMINI_API_KEY = _get_str("GEMINI_API_KEY", "")
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


# -------- Cog/shared config (formerly server_configs/cogs_config.py) --------

# Admins
admin_user_ids = _get_json_int_list("ADMIN_USER_IDS")

# Error alerts (Discord ping + embed). Both zero = disabled.
# Prefer a staff channel for ERROR_ALERT_CHANNEL_ID so delivery does not depend on DMs.
ERROR_ALERT_USER_ID = _get_int("ERROR_ALERT_USER_ID", 0)
ERROR_ALERT_CHANNEL_ID = _get_int("ERROR_ALERT_CHANNEL_ID", 0)

# Channel IDs
voice_channel_ids = _get_json_int_list("VOICE_CHANNEL_IDS")
create_fireteam_channel_id = _get_int("CREATE_FIRETEAM_CHANNEL_ID", 0)
watch_party_channel_id = _get_int("WATCH_PARTY_CHANNEL_ID", 0)
watch_party_event_id = _get_int("WATCH_PARTY_EVENT_ID", 0)
league_channel_id = _get_int("LEAGUE_CHANNEL_ID", 0)
backup_channel_id = _get_int("BACKUP_CHANNEL_ID", 0)
bot_spam_id = _get_int("BOT_SPAM_ID", 0)
afk_channel_id = _get_int("AFK_CHANNEL_ID", 0)

# Category IDs
seen_category_id = _get_int("SEEN_CATEGORY_ID", 0)
hidden_category_id = _get_int("HIDDEN_CATEGORY_ID", 0)
waterboard_category_id = _get_int("WATERBOARD_CATEGORY_ID", 0)

# API keys
OMDB_API_KEY = _get_str("OMDB_API_KEY", "")
OMDB_API_URL = _get_str("OMDB_API_URL", "")
BRAVE_SEARCH_API_KEY = _get_str("BRAVE_SEARCH_API_KEY", "")

# Emoji IDs
heads_emoji_id = _get_int("HEADS_EMOJI_ID", 0)
tails_emoji_id = _get_int("TAILS_EMOJI_ID", 0)

# Birthdays
birthday_announcement_channel_id = _get_int("BIRTHDAY_ANNOUNCEMENT_CHANNEL_ID", 0)
birthday_reaction_channel_id = _get_int("BIRTHDAY_REACTION_CHANNEL_ID", 0)
birthday_role_id = _get_int("BIRTHDAY_ROLE_ID", 0)
birthday_emoji_id = _get_int("BIRTHDAY_EMOJI_ID", 0)
birthday_channel_id = _get_int("BIRTHDAY_CHANNEL_ID", 0)

# TCG config (JSON)
MANA_SYMBOLS = _get_json_dict("MANA_SYMBOLS")

# MTG autocard in allowed channels only; empty list = disabled
mtg_autolink_channel_ids = frozenset(_get_json_int_list("MTG_AUTOLINK_CHANNEL_IDS"))
mtg_autolink_blocked_names = _frozenset_lower(_get_json_str_list("MTG_AUTOLINK_BLOCKED_NAMES"))
mtg_autolink_max_cards_per_message = _get_int("MTG_AUTOLINK_MAX_CARDS_PER_MESSAGE", 5) # Not in Doppler
mtg_autolink_max_word_span = max(1, min(_get_int("MTG_AUTOLINK_MAX_WORD_SPAN", 4), 8)) # Not in Doppler

# Say config (JSON + strings)
webhook_url = _get_str("WEBHOOK_URL", "")
character_avatars = _get_json_dict("CHARACTER_AVATARS")
ZERONI_REACTION_EMOJI = _get_str("ZERONI_REACTION_EMOJI", "")
COMMUNITY_NOTES_REACTION_EMOJI = _get_str("COMMUNITY_NOTES_REACTION_EMOJI", "")

# Bot log viewer (.logging): optional systemd unit on Linux (e.g. discord_bot), else tail BOT_LOG_FILE or nextcord.log.
# BOT_LOG_JOURNAL_EXTRA_UNITS: comma-separated units for additional panes (e.g. lavalink.service).
BOT_LOG_JOURNAL_UNIT = _get_str("BOT_LOG_JOURNAL_UNIT", "")
BOT_LOG_JOURNAL_EXTRA_UNITS = _get_str("BOT_LOG_JOURNAL_EXTRA_UNITS", "")
BOT_LOG_FILE = _get_str("BOT_LOG_FILE", "") # Not in Doppler
