"""Guild-scoped settings stored in Postgres (DB-only; no runtime env fallback).

Process secrets and infra remain in env via ``server_configs.config``.
Guild snowflakes / feature knobs live here and are edited via ``.setup``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import asyncpg
import nextcord

from main_bot.server_configs.config import GUILD_ID, _get_int, _get_json_int_list, _get_json_str_list, _get_str

_LOG = logging.getLogger(__name__)

_SCHEMA = "guild_config"
SKIPPED_GROUPS_KEY = "skipped_groups"


@dataclass(frozen=True)
class SettingDef:
    key: str
    value_type: str  # int | int_list | str | str_list
    default: Any
    group: str
    env_name: str = ""
    label: str = ""


# Keys editable via .setup / import-env. CHARACTER_AVATARS / MANA_SYMBOLS stay in env (v1).
SETTING_DEFS: tuple[SettingDef, ...] = (
    SettingDef("bot_admin_role_ids", "int_list", [], "roles", "", "Bot admin roles"),
    SettingDef("bot_spam_id", "int", 0, "channels", "BOT_SPAM_ID", "Bot spam channel"),
    SettingDef("backup_channel_id", "int", 0, "channels", "BACKUP_CHANNEL_ID", "Backup channel"),
    SettingDef("error_alert_channel_id", "int", 0, "alerts", "ERROR_ALERT_CHANNEL_ID", "Error alert channel"),
    SettingDef("error_alert_user_id", "int", 0, "alerts", "ERROR_ALERT_USER_ID", "Error alert user"),
    SettingDef("voice_channel_ids", "int_list", [], "voice", "VOICE_CHANNEL_IDS", "Voice channel IDs"),
    SettingDef(
        "create_fireteam_channel_id",
        "int",
        0,
        "voice",
        "CREATE_FIRETEAM_CHANNEL_ID",
        "Create fireteam channel",
    ),
    SettingDef(
        "watch_party_channel_id",
        "int",
        0,
        "voice",
        "WATCH_PARTY_CHANNEL_ID",
        "Watch party channel",
    ),
    SettingDef("league_channel_id", "int", 0, "voice", "LEAGUE_CHANNEL_ID", "League channel"),
    SettingDef("afk_channel_id", "int", 0, "voice", "AFK_CHANNEL_ID", "AFK channel"),
    SettingDef("seen_category_id", "int", 0, "voice", "SEEN_CATEGORY_ID", "Seen category"),
    SettingDef("hidden_category_id", "int", 0, "voice", "HIDDEN_CATEGORY_ID", "Hidden category"),
    SettingDef(
        "waterboard_category_id",
        "int",
        0,
        "waterboard",
        "WATERBOARD_CATEGORY_ID",
        "Waterboard category",
    ),
    SettingDef(
        "music_voice_channel_denylist",
        "int_list",
        [],
        "voice",
        "MUSIC_VOICE_CHANNEL_DENYLIST",
        "Music voice denylist",
    ),
    SettingDef("heads_emoji_id", "int", 0, "economy_emojis", "HEADS_EMOJI_ID", "Heads emoji"),
    SettingDef("tails_emoji_id", "int", 0, "economy_emojis", "TAILS_EMOJI_ID", "Tails emoji"),
    SettingDef("coin_emoji_id", "int", 0, "economy_emojis", "COIN_EMOJI_ID", "Coin emoji"),
    SettingDef(
        "birthday_announcement_channel_id",
        "int",
        0,
        "birthday",
        "BIRTHDAY_ANNOUNCEMENT_CHANNEL_ID",
        "Birthday announcement channel",
    ),
    SettingDef(
        "birthday_reaction_channel_id",
        "int",
        0,
        "birthday",
        "BIRTHDAY_REACTION_CHANNEL_ID",
        "Birthday reaction channel",
    ),
    SettingDef("birthday_role_id", "int", 0, "birthday", "BIRTHDAY_ROLE_ID", "Birthday role"),
    SettingDef("birthday_emoji_id", "int", 0, "birthday", "BIRTHDAY_EMOJI_ID", "Birthday emoji"),
    SettingDef(
        "birthday_channel_id",
        "int",
        0,
        "birthday",
        "BIRTHDAY_CHANNEL_ID",
        "Birthday channel (debug)",
    ),
    SettingDef(
        "mtg_autolink_channel_ids",
        "int_list",
        [],
        "mtg",
        "MTG_AUTOLINK_CHANNEL_IDS",
        "MTG autolink channels",
    ),
    SettingDef(
        "mtg_autolink_cooldown_channel_ids",
        "int_list",
        [],
        "mtg",
        "MTG_AUTOLINK_COOLDOWN_CHANNEL_IDS",
        "MTG cooldown channels",
    ),
    SettingDef(
        "mtg_autolink_blocked_names",
        "str_list",
        [],
        "mtg",
        "MTG_AUTOLINK_BLOCKED_NAMES",
        "MTG blocked names",
    ),
    SettingDef(
        "mtg_autolink_max_cards_per_message",
        "int",
        5,
        "mtg",
        "MTG_AUTOLINK_MAX_CARDS_PER_MESSAGE",
        "MTG max cards / message",
    ),
    SettingDef(
        "mtg_autolink_max_word_span",
        "int",
        4,
        "mtg",
        "MTG_AUTOLINK_MAX_WORD_SPAN",
        "MTG max word span",
    ),
    SettingDef(
        "zeroni_reaction_emoji",
        "str",
        "",
        "say_reactions",
        "ZERONI_REACTION_EMOJI",
        "Zeroni reaction emoji",
    ),
    SettingDef(
        "community_notes_reaction_emoji",
        "str",
        "",
        "say_reactions",
        "COMMUNITY_NOTES_REACTION_EMOJI",
        "Community Notes reaction emoji",
    ),
    SettingDef(SKIPPED_GROUPS_KEY, "str_list", [], "_meta", "", "Skipped feature groups"),
)

SETTING_BY_KEY: Dict[str, SettingDef] = {d.key: d for d in SETTING_DEFS}

FEATURE_GROUPS: tuple[tuple[str, str], ...] = (
    ("roles", "Bot admin roles"),
    ("channels", "Channels"),
    ("voice", "Voice / categories"),
    ("waterboard", "Waterboard"),
    ("birthday", "Birthday"),
    ("economy_emojis", "Economy / gambling emojis"),
    ("mtg", "MTG autocard"),
    ("say_reactions", "Say reactions"),
    ("alerts", "Error alerts"),
)

GROUP_KEYS: Dict[str, List[str]] = {}
for _def in SETTING_DEFS:
    if _def.group == "_meta":
        continue
    GROUP_KEYS.setdefault(_def.group, []).append(_def.key)


def _default_for(key: str) -> Any:
    d = SETTING_BY_KEY.get(key)
    if d is None:
        return None
    default = d.default
    if isinstance(default, list):
        return list(default)
    return default


def _normalize_value(defn: SettingDef, value: Any) -> Any:
    if defn.value_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(defn.default or 0)
    if defn.value_type == "int_list":
        if value is None:
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        out: List[int] = []
        for item in value:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    if defn.value_type == "str_list":
        if value is None:
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return [value] if value else []
        return [str(x) for x in value]
    if defn.value_type == "str":
        return "" if value is None else str(value)
    return value


def read_env_value_for_import(defn: SettingDef) -> Any:
    """Read a migratable key from process env for ``.setup import-env`` (one-shot)."""
    if not defn.env_name:
        return _default_for(defn.key)
    if defn.value_type == "int":
        return _get_int(defn.env_name, int(defn.default or 0))
    if defn.value_type == "int_list":
        return _get_json_int_list(defn.env_name)
    if defn.value_type == "str_list":
        return _get_json_str_list(defn.env_name)
    return _get_str(defn.env_name, str(defn.default or ""))


def env_value_is_nondefault(defn: SettingDef, value: Any) -> bool:
    default = defn.default
    if defn.value_type in ("int_list", "str_list"):
        return bool(value)
    if defn.value_type == "int":
        return int(value or 0) != int(default or 0)
    return bool(value) and value != default


class GuildSettings:
    """In-memory cache of guild setting_values for GUILD_ID."""

    def __init__(self, guild_id: int, values: Optional[Mapping[str, Any]] = None) -> None:
        self.guild_id = guild_id
        self._values: Dict[str, Any] = dict(values or {})

    @classmethod
    def empty(cls, guild_id: int = 0) -> "GuildSettings":
        return cls(guild_id or GUILD_ID, {})

    def raw(self) -> Dict[str, Any]:
        return dict(self._values)

    def has(self, key: str) -> bool:
        return key in self._values

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._values:
            defn = SETTING_BY_KEY.get(key)
            if defn:
                return _normalize_value(defn, self._values[key])
            return self._values[key]
        if default is not None:
            return default
        return _default_for(key)

    def get_int(self, key: str) -> int:
        return int(self.get(key) or 0)

    def get_int_list(self, key: str) -> List[int]:
        val = self.get(key)
        return list(val) if isinstance(val, list) else []

    def get_str(self, key: str) -> str:
        return str(self.get(key) or "")

    def get_str_list(self, key: str) -> List[str]:
        val = self.get(key)
        return list(val) if isinstance(val, list) else []

    def skipped_groups(self) -> Set[str]:
        return {s.lower() for s in self.get_str_list(SKIPPED_GROUPS_KEY)}

    def is_group_skipped(self, group: str) -> bool:
        return group.lower() in self.skipped_groups()

    def group_status(self, group: str) -> str:
        """Return configured | missing | skipped for a feature group."""
        if self.is_group_skipped(group):
            return "skipped"
        keys = GROUP_KEYS.get(group, [])
        if not keys:
            return "missing"
        # roles: empty list is valid (Administrator-only)
        if group == "roles":
            return "configured" if self.has("bot_admin_role_ids") else "missing"
        # lists that mean "off when empty": configured if key present OR we don't require them
        requiredish = [
            k
            for k in keys
            if SETTING_BY_KEY[k].value_type == "int"
            or (
                SETTING_BY_KEY[k].value_type == "str"
                and SETTING_BY_KEY[k].default == ""
            )
        ]
        if not requiredish:
            # only list keys — present in DB counts as configured even if empty
            return "configured" if any(self.has(k) for k in keys) else "missing"
        for k in requiredish:
            defn = SETTING_BY_KEY[k]
            if defn.value_type == "int" and self.get_int(k):
                return "configured"
            if defn.value_type == "str" and self.get_str(k):
                return "configured"
        # if any non-default list is set, treat as configured
        for k in keys:
            defn = SETTING_BY_KEY[k]
            if defn.value_type in ("int_list", "str_list") and self.get(k):
                return "configured"
        return "missing"


_cached: Optional[GuildSettings] = None


def get_settings() -> GuildSettings:
    global _cached
    if _cached is None:
        return GuildSettings.empty()
    return _cached


def set_cached_settings(settings: GuildSettings) -> None:
    global _cached
    _cached = settings


async def load_guild_settings(pool: asyncpg.Pool, guild_id: int = 0) -> GuildSettings:
    gid = guild_id or GUILD_ID
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f'''
            SELECT key, value
            FROM "{_SCHEMA}".setting_values
            WHERE guild_id = $1
            ''',
            gid,
        )
    values: Dict[str, Any] = {}
    for row in rows:
        key = row["key"]
        raw = row["value"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                pass
        values[key] = raw
    settings = GuildSettings(gid, values)
    set_cached_settings(settings)
    return settings


async def ensure_settings_row(
    pool: asyncpg.Pool, guild_id: int, updated_by: Optional[int] = None
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            f'''
            INSERT INTO "{_SCHEMA}".settings (guild_id, updated_at, updated_by)
            VALUES ($1, NOW(), $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET updated_at = NOW(),
                updated_by = COALESCE($2, "{_SCHEMA}".settings.updated_by)
            ''',
            guild_id,
            updated_by,
        )


async def set_setting(
    pool: asyncpg.Pool,
    key: str,
    value: Any,
    *,
    guild_id: int = 0,
    updated_by: Optional[int] = None,
) -> GuildSettings:
    gid = guild_id or GUILD_ID
    defn = SETTING_BY_KEY.get(key)
    if defn is None:
        raise KeyError(f"Unknown setting key: {key}")
    normalized = _normalize_value(defn, value)
    await ensure_settings_row(pool, gid, updated_by)
    async with pool.acquire() as conn:
        await conn.execute(
            f'''
            INSERT INTO "{_SCHEMA}".setting_values (guild_id, key, value)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (guild_id, key) DO UPDATE SET value = EXCLUDED.value
            ''',
            gid,
            key,
            json.dumps(normalized),
        )
    return await load_guild_settings(pool, gid)


async def clear_setting(
    pool: asyncpg.Pool,
    key: str,
    *,
    guild_id: int = 0,
    updated_by: Optional[int] = None,
) -> GuildSettings:
    gid = guild_id or GUILD_ID
    await ensure_settings_row(pool, gid, updated_by)
    async with pool.acquire() as conn:
        await conn.execute(
            f'''
            DELETE FROM "{_SCHEMA}".setting_values
            WHERE guild_id = $1 AND key = $2
            ''',
            gid,
            key,
        )
    return await load_guild_settings(pool, gid)


async def set_group_skipped(
    pool: asyncpg.Pool,
    group: str,
    skipped: bool,
    *,
    guild_id: int = 0,
    updated_by: Optional[int] = None,
) -> GuildSettings:
    current = get_settings()
    groups = set(current.skipped_groups())
    g = group.lower()
    if skipped:
        groups.add(g)
    else:
        groups.discard(g)
    return await set_setting(
        pool, SKIPPED_GROUPS_KEY, sorted(groups), guild_id=guild_id, updated_by=updated_by
    )


async def import_env_into_db(
    pool: asyncpg.Pool,
    *,
    guild_id: int = 0,
    updated_by: Optional[int] = None,
    overwrite: bool = True,
) -> tuple[GuildSettings, List[str]]:
    """One-shot copy of non-default env values into DB. Returns (settings, keys_written)."""
    gid = guild_id or GUILD_ID
    written: List[str] = []
    current = await load_guild_settings(pool, gid)
    for defn in SETTING_DEFS:
        if defn.group == "_meta" or not defn.env_name:
            continue
        value = read_env_value_for_import(defn)
        if not env_value_is_nondefault(defn, value):
            continue
        if not overwrite and current.has(defn.key):
            continue
        await set_setting(pool, defn.key, value, guild_id=gid, updated_by=updated_by)
        written.append(defn.key)
    return await load_guild_settings(pool, gid), written


def is_bot_admin(member: nextcord.Member, settings: Optional[GuildSettings] = None) -> bool:
    """Discord Administrator OR optional bot_admin_role_ids from .setup."""
    if getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
        return True
    gs = settings or get_settings()
    role_ids = set(gs.get_int_list("bot_admin_role_ids"))
    if not role_ids:
        return False
    return any(role.id in role_ids for role in getattr(member, "roles", []))


def config_missing_message(group: str, *, skipped: bool = False) -> str:
    if skipped:
        return f"This feature is disabled for this server (`{group}` skipped in `.setup`)."
    return (
        f"This feature isn’t configured. An admin can run `.setup` → {group}, "
        f"or mark it Skipped."
    )


def mtg_autolink_channel_ids(settings: Optional[GuildSettings] = None) -> frozenset[int]:
    gs = settings or get_settings()
    explicit = set(gs.get_int_list("mtg_autolink_channel_ids"))
    cooldown = set(gs.get_int_list("mtg_autolink_cooldown_channel_ids"))
    return frozenset(explicit | cooldown)


def music_voice_denylist_ids(settings: Optional[GuildSettings] = None) -> frozenset[int]:
    gs = settings or get_settings()
    return frozenset(gs.get_int_list("music_voice_channel_denylist"))
