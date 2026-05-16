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

- `COIN_EMOJI_ID` (int): guild custom emoji ID used on brainrot “purchase” buttons (fallback is Unicode 🪙 if unset/`0`).
- `LAVALINK_URI` (string): Lavalink HTTP/WS endpoint for **non‑Compose** runs (Python on your laptop, etc.); default `http://127.0.0.1:2333` in `config.py`. **Inside Docker**, do **not** rely on a Doppler `LAVALINK_URI` of `localhost` unless you deliberately override Compose: from the bot container, `localhost` is the bot, not Lavalink. The bundled `docker-compose.yml` wires the bot to `http://lavalink:2333` via Compose substitution (`LAVALINK_DOCKER_URI` only if Lavalink runs outside that Compose stack).
- `LAVALINK_PASSWORD` (string): **Must match** Lavalink `application.yml` → `lavalink.server.password`. If unset, the bot defaults to `youshallnotpass` (see `config.py`). A mismatch produces Lavalink log `Authentication failed` on `/v4/websocket` and wavelink `Failed to authenticate Node`.
- `MUSIC_LOCAL_HTTP_HOST` (string): Hostname or IP **embedded in HTTP URLs** the bot gives Lavalink for `local_audio/music/...` tracks (default `127.0.0.1`). In Docker Compose, set this to the **bot service hostname** Lavalink can resolve (often `bot`).
- `MUSIC_LOCAL_HTTP_BIND_HOST` (string, optional): Address for aiohttp to **listen** on; if unset/empty, matches `MUSIC_LOCAL_HTTP_HOST`. Use `0.0.0.0` in containers so other services can connect while URLs still use `MUSIC_LOCAL_HTTP_HOST`.
- `MUSIC_LOCAL_HTTP_PORT` (int): Port for that HTTP server (default `8765`).
- `MUSIC_FOLDER_1` … `MUSIC_FOLDER_25` (strings): Register `local_audio/music/<name>` as top-level slash command `/<name>` (see `README.md`). Reserved: `gaming`, `brainrot`. **Docker:** each key must appear under `services.bot.environment` in `docker-compose.yml` (copy the `MUSIC_FOLDER_n` + `MUSIC_n_SHUFFLE_START` stanza); the bundled file forwards slots 1–3 as templates for up to 25.
- `MUSIC_VOICE_CHANNEL_DENYLIST` (JSON array of int channel IDs, optional): Blocks slash music / VC controls in those channels.
- `GEMINI_API_KEY` (string)
- `ENVIRONMENT` (string: `development` or `production`) used by `is_development_environment()`
- `LOAD_DEVELOPMENT_COGS` (optional): when set to `1`, `true`, `yes`, or `on`, the bot loads extensions under `main_bot.cogs.development` in addition to `production`. When set to `0`, `false`, `no`, or `off`, development extensions are not loaded even if `DEVELOPMENT_COG_EXTENSIONS_ENABLED` is True in `main.py`. If unset, the default comes from `DEVELOPMENT_COG_EXTENSIONS_ENABLED` in `main_bot/main.py`.
- `FULL_DEBUG_IN_TERMINAL` (optional): same truthy/falsy tokens as `LOAD_DEVELOPMENT_COGS`. When truthy, selected cogs emit verbose `[DEBUG]` lines via **`main_bot`** logging (**`cog_print`**) with optional **`APP_LOG_STDOUT_MIRROR`** echo. If unset, defaults to **false**.
- `NEXTCORD_FILE_LOG_LEVEL` (optional): `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` for the **Nextcord library** subtree of the **combined rotating file** resolved by **`BOT_LOG_FILE`** (default `<project>/logs/bot-runtime.log`; Docker Compose often sets **`BOT_LOG_FILE=/app/logs/bot-runtime.log`** with **`./logs`** bind-mounted — see **`/logging`** when not using journal). Default **INFO**. **`DEBUG`** is extremely noisy under Docker/Gateway spam.

## Admin `.logging` command (`main_bot.cogs.production.logging`)

- `BOT_LOG_JOURNAL_UNIT` (optional): systemd unit name for `journalctl -u …` (e.g. `discord_bot`). Must match the **actual** unit on the server. If your service was renamed from `discord_bot_v2` to `discord_bot`, update this in Doppler or `.logging` will show empty journal tails.
- `BOT_LOG_JOURNAL_EXTRA_UNITS` (optional): comma-separated extra units (e.g. `lavalink`) for additional embeds.
- If `BOT_LOG_JOURNAL_UNIT` is **unset or empty**, the cog tails the **combined** runtime log file: **`BOT_LOG_FILE`**, or when that is unset the default **`logs/bot-runtime.log`** under the project/app root (`main_bot.paths.runtime_bot_log_path()`).
- `BOT_LOG_FILE` (optional): explicit path for that file when not using journal. Docker Compose typically sets **`/app/logs/bot-runtime.log`** with **`./logs`** bind-mounted to **`/app/logs`**.
- `BOT_LOG_MAX_BYTES` / `BOT_LOG_BACKUP_COUNT` (optional): rotation for **`RotatingFileHandler`** in `main_bot/main.py` — defaults **`10485760`** / **`5`** unless overridden in Compose.
- `APP_LOG_LEVEL` (optional): verbosity for **`main_bot.*`** in the **same** combined file (`DEBUG`, `INFO`, …). Default **`INFO`**.
- `APP_LOG_STDOUT_MIRROR` (optional): when truthy (Compose default `true`), **`boot_print`** / **`cog_print`** also echo **`[BOT_STARTING]`** / prefixed lines to stdout (**`docker compose logs`**).


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

- `MTG_AUTOLINK_CHANNEL_IDS` (JSON array of int channel IDs): extra autocard-enabled channels beyond the cooldown list. **Effective allowlist is** `MTG_AUTOLINK_CHANNEL_IDS` **∪** `MTG_AUTOLINK_COOLDOWN_CHANNEL_IDS`; if **both are empty**, autocard is off.

- `MTG_AUTOLINK_COOLDOWN_CHANNEL_IDS` (JSON array of int channel IDs): channels throttled to at most one autocard reply every **90 seconds**, shared across everyone in that channel. **These IDs are also treated as autocard-enabled** (unioned with `MTG_AUTOLINK_CHANNEL_IDS`), so you can list “general chat” here even if it is omitted from `MTG_AUTOLINK_CHANNEL_IDS`. Empty or omitted = no throttle anywhere.
- `MTG_AUTOLINK_BLOCKED_NAMES` (optional JSON string array)
- `MANA_SYMBOLS` (JSON object)
- `WEBHOOK_URL` (string)
- `CHARACTER_AVATARS` (JSON object)
- `ZERONI_REACTION_EMOJI` (string)
- `COMMUNITY_NOTES_REACTION_EMOJI` (string)

