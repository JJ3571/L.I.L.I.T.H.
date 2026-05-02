# Doppler env keys (Discord-Bot-Sandbox)

This bot loads config from environment variables (typically injected by Doppler).

## Conventions

- **Strings**: set as normal env vars (e.g. `DISCORD_BOT_TOKEN=...`).
- **Integers (IDs)**: stored as strings but parsed to int in Python (e.g. `GUILD_ID=421980223391924227`).
- **Lists / Dicts**: stored as **JSON-like text** in Doppler.
  - Lists use `[]` (example: `ADMIN_USER_IDS=[255226353278910464,282739692057788426]`)
  - Dicts use `{}` (example: `CHARACTER_AVATARS={"Master Chief":"https://...","Cortana":"https://..."}`)
  - `# comments` are allowed (they are stripped during parsing), so you can keep e.g.

```text
[
  255226353278910464, # Chill
  282739692057788426, # Crzifox
  321888250136363009, # JJ
  220656152994643969  # Nut
]
```

## Required (core bot)

- `DISCORD_BOT_TOKEN` (string)
- `GUILD_ID` (int)
- `APPLICATION_ID` (int)
- `DATABASE_URL` (string): `postgresql://...` for asyncpg. Neon and most cloud hosts need TLS; use the dashboard connection string with `?sslmode=require` (or rely on the bot normalizing non-local URLs to append `sslmode=require` if it was omitted). If you still see “connection reset” during startup, check Neon project status, IP allowlisting, and VPN/firewall.

## Optional (feature-dependent)

- `GEMINI_API_KEY` (string)
- `ENVIRONMENT` (string: `development` or `production`) used by `is_development_environment()`
- `LOAD_DEVELOPMENT_COGS` (optional): when set to `1`, `true`, `yes`, or `on`, the bot loads extensions under `main_bot.cogs.development` in addition to `production`. When set to `0`, `false`, `no`, or `off`, development extensions are not loaded even if `DEVELOPMENT_COG_EXTENSIONS_ENABLED` is True in `main.py`. If unset, the default comes from `DEVELOPMENT_COG_EXTENSIONS_ENABLED` in `main_bot/main.py`.

## Admin `.logging` command (`main_bot.cogs.production.logging`)

- `BOT_LOG_JOURNAL_UNIT` (optional): systemd unit name for `journalctl -u …` (e.g. `discord_bot`). Must match the **actual** unit on the server. If your service was renamed from `discord_bot_v2` to `discord_bot`, update this in Doppler or `.logging` will show empty journal tails.
- `BOT_LOG_JOURNAL_EXTRA_UNITS` (optional): comma-separated extra units (e.g. `lavalink`) for additional embeds.
- If `BOT_LOG_JOURNAL_UNIT` is **unset or empty**, the cog tails **`nextcord.log`** in the repo root instead (same file as `tail -f` on the VPS).
- `BOT_LOG_FILE` (optional): override path for file tailing when not using journal (see `main_bot/server_configs/config.py`).

## Crafty Controller

- `CRAFTY_BASE_URL` (string)
- `CRAFTY_USERNAME` (string)
- `CRAFTY_PASSWORD` (string)

## Shared lists

- `ADMIN_USER_IDS` (JSON array of ints)
- `VOICE_CHANNEL_IDS` (JSON array of ints)

## Channels / categories / roles / emojis (ints)

- `CREATE_FIRETEAM_CHANNEL_ID`
- `WATCH_PARTY_CHANNEL_ID`
- `WATCH_PARTY_EVENT_ID`
- `LEAGUE_CHANNEL_ID`
- `BACKUP_CHANNEL_ID`
- `BOT_SPAM_ID`
- `AFK_CHANNEL_ID`
- `SEEN_CATEGORY_ID`
- `HIDDEN_CATEGORY_ID`
- `HEADS_EMOJI_ID`
- `TAILS_EMOJI_ID`
- `BIRTHDAY_ANNOUNCEMENT_CHANNEL_ID`
- `BIRTHDAY_REACTION_CHANNEL_ID`
- `BIRTHDAY_ROLE_ID`
- `BIRTHDAY_EMOJI_ID`
- `BIRTHDAY_CHANNEL_ID` (optional legacy alias used by `cogs/debugging/role_debug.py`)

## External APIs

- `OMDB_API_KEY` (string)
- `OMDB_API_URL` (string)
- `BRAVE_SEARCH_API_KEY` (string)
- `BRAVE_IMAGE_SEARCH_MIN_INTERVAL` (optional, seconds) — default `1.05`; Brave Image Search free tier is ~1 request/s, so the bot serializes image searches. Increase if you still see `429` from Brave.

## TCG / Say (JSON + strings)

- `MTG_AUTOLINK_CHANNEL_IDS` (JSON array of int channel IDs): where MTG autocard replies are enabled; empty disables.
- `MTG_AUTOLINK_COOLDOWN_CHANNEL_IDS` (JSON array of int channel IDs): channels where at most one autocard reply runs every **180 seconds**, grouped across everyone in that channel (omit IDs for unrestricted channels like a dedicated MTG room). Empty or omitted = **no throttle** anywhere.
- `MTG_AUTOLINK_BLOCKED_NAMES` (optional JSON string array)
- `MANA_SYMBOLS` (JSON object)
- `WEBHOOK_URL` (string)
- `CHARACTER_AVATARS` (JSON object)
- `ZERONI_REACTION_EMOJI` (string)
- `COMMUNITY_NOTES_REACTION_EMOJI` (string)

