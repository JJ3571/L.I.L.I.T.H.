# Configuration

This document lists every environment variable that the bot and Docker Compose use. The template file is `[.env.example](../.env.example)`. Copy that file to `.env` before you start the stack.

Guild channel, role, category, emoji, MTG channel lists, error-alert IDs, and optional bot-admin roles are **not** set here. Configure them in Discord with the prefix command **`.setup`** (stored in Postgres). See [QUICKSTART.md](QUICKSTART.md).

Optional Doppler notes: [SECRETS_DOPPLER.md](SECRETS_DOPPLER.md). Prefer downloading secrets into `.env` rather than `doppler run` injection.

## Secret Conventions

- Strings use normal `KEY=value` lines.
- Integer IDs are stored as text. Python parses them to integers.
- Lists use JSON array text. Example: `MUSIC_FOLDER` slots are plain strings; API-related lists are rare in env now.
- Objects use JSON object text. Example: `CHARACTER_AVATARS={"Name":"https://..."}`
- Hash comments inside JSON text are allowed. The parser functions remove them.

## Always Required


| Key                 | Type   | Description               |
| ------------------- | ------ | ------------------------- |
| `DISCORD_BOT_TOKEN` | string | Discord bot token         |
| `APPLICATION_ID`    | int    | Discord application ID    |
| `GUILD_ID`          | int    | Discord guild (server) ID |


## Database


| Key                  | Type   | Description                                                                                                                                                     |
| -------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`       | string | PostgreSQL URL for asyncpg. Leave this empty with the `bundled-db` profile. If you disable `bundled-db`, set this key to a full URL directed at your database. |
| `COMPOSE_PROFILES`   | string | Docker Compose profiles. Default `bundled-db`. Use `bundled-db,admin-ui` for pgAdmin. Leave it blank for an external database only.                           |
| `POSTGRES_USER`      | string | Bundled Postgres user Default: `bot`                                                                                                                           |
| `POSTGRES_PASSWORD`  | string | Bundled Postgres password Default: `bot`                                                                                                                       |
| `POSTGRES_DB`        | string | Bundled Postgres database name Default: `discord_bot`                                                                                                           |
| `POSTGRES_HOST_PORT` | int    | Host loopback port for bundled Postgres Default: `5432`                                                                                                        |
| `PGADMIN_EMAIL`      | string | pgAdmin login email (`admin-ui` profile)                                                                                                                        |
| `PGADMIN_PASSWORD`   | string | pgAdmin login password                                                                                                                                          |
| `PGADMIN_HOST_PORT`  | int    | Host port for pgAdmin (default `5050`)                                                                                                                          |


Cloud hosts often need TLS. Append `?sslmode=require` to the database URL. Hostname `postgres` skips auto-TLS.

See [DATABASE.md](DATABASE.md) for profiles and migration.

## Docker Compose substitution only

These keys are used by `docker compose` for variable interpolation. They are not read by Python unless also listed under `services.bot.environment` in `docker-compose.yml`.

- `COMPOSE_PROFILES`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST_PORT`
- `PGADMIN_EMAIL`, `PGADMIN_PASSWORD`, `PGADMIN_HOST_PORT`
- `LAVALINK_DOCKER_URI` (optional override for Lavalink outside Compose)

## Runtime toggles


| Key                       | Description                                                                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `LOAD_DEVELOPMENT_COGS`   | When true, load `main_bot.cogs.development`. When false, skip those extensions. When unset, use the default in `main_bot/main.py`. |
| `FULL_DEBUG_IN_TERMINAL`  | When true, selected cogs emit verbose debug lines. Default false.                                                                   |
| `NEXTCORD_FILE_LOG_LEVEL` | Nextcord logger level in the combined file. Values: DEBUG, INFO, WARNING, ERROR, CRITICAL. Default INFO.                            |
| `APP_LOG_LEVEL`           | Verbosity for `main_bot.*` in the same file. Default INFO.                                                                          |
| `APP_LOG_STDOUT_MIRROR`   | When true, boot and cog lines also echo to stdout. Compose default true.                                                            |
| `ENVIRONMENT`             | `development` or `production`.                                                                                                       |


True can be: `1`, `true`, `yes`, `on` -- False can be: `0`, `false`, `no`, `off`.

## Lavalink and local music


| Key                                  | Description                                                                                                                                                            |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LAVALINK_URI`                       | Lavalink HTTP endpoint for host Python runs. Default `http://127.0.0.1:2333`. Inside Docker, Compose sets `http://lavalink:2333` unless you set `LAVALINK_DOCKER_URI`. |
| `LAVALINK_PASSWORD`                  | Must match `lavalink.server.password` in `application.yml`. Default `youshallnotpass`.                                                                                 |
| `YOUTUBE_OAUTH_ENABLED`              | `true` or `false`. Passed to the Lavalink container. Default false.                                                                                                    |
| `YOUTUBE_OAUTH_REFRESH_TOKEN`        | Refresh token after the OAuth device flow.                                                                                                                             |
| `MUSIC_LOCAL_HTTP_HOST`              | Hostname in HTTP URLs that the bot gives Lavalink. Default `127.0.0.1`. In Compose, use the bot service hostname (often `bot`).                                        |
| `MUSIC_LOCAL_HTTP_BIND_HOST`         | Address for aiohttp to listen on. Use `0.0.0.0` in containers.                                                                                                         |
| `MUSIC_LOCAL_HTTP_PORT`              | Port for the local music HTTP server. Default `8765`.                                                                                                                  |
| `MUSIC_FOLDER_1` … `MUSIC_FOLDER_25` | Flat folder names under `local_audio/music/`. Each registers a slash command. Reserved: `gaming`, `brainrot`.                                                          |
| `MUSIC_n_SHUFFLE_START`              | When true, seek to a random position in each track for folder `n`.                                                                                                     |


Music voice denylist channels are configured via `.setup` (Postgres), not env.

Docker Compose only forwards keys listed under `services.bot.environment`. The bundled file forwards slots 1–3. Copy that same pattern for slots 4–25.

See [MUSIC.md](MUSIC.md).

## Admin logging


| Key                           | Description                                                                      |
| ----------------------------- | -------------------------------------------------------------------------------- |
| `BOT_LOG_JOURNAL_UNIT`        | systemd unit name for journal tails. Empty means use the log file.               |
| `BOT_LOG_JOURNAL_EXTRA_UNITS` | Comma-separated extra units.                                                     |
| `BOT_LOG_FILE`                | Path for the combined rotating log. Compose default `/app/logs/discord_bot.log`. |
| `BOT_LOG_MAX_BYTES`           | Rotation size. Default `10485760`.                                               |
| `BOT_LOG_BACKUP_COUNT`        | Rotation count. Default `5`.                                                     |


## Crafty Controller


| Key               | Description         |
| ----------------- | ------------------- |
| `CRAFTY_BASE_URL` | Crafty API base URL |
| `CRAFTY_USERNAME` | Crafty username     |
| `CRAFTY_PASSWORD` | Crafty password     |


## External APIs


| Key                                 | Description                                           |
| ----------------------------------- | ----------------------------------------------------- |
| `OPENCODE_API_KEY`                  | OpenCode Go API key for the Say cog                   |
| `OPENCODE_MODEL`                    | Model id. Default `glm-5.3-flash`                     |
| `OMDB_API_KEY`                      | OMDb API key                                          |
| `OMDB_API_URL`                      | OMDb API URL                                          |
| `BRAVE_SEARCH_API_KEY`              | Brave Search key                                      |
| `BRAVE_IMAGE_SEARCH_MIN_INTERVAL`   | Seconds between Brave image calls. Default `1.05`     |
| `BRAVE_TIERLIST_IMAGE_MIN_HEIGHT`   | Minimum image height for tier lists                   |
| `BRAVE_TIERLIST_IMAGE_MIN_WIDTH`    | Minimum image width for tier lists                    |
| `SERPENT_API_KEY`                   | Serpent API key for Google Images                     |
| `SERPENT_IMAGE_SEARCH_MIN_INTERVAL` | Seconds between Serpent calls. Default `1.05`         |
| `SERPENT_IMAGE_ENGINE`              | `google`, `bing`, `yahoo`, or `ddg`. Default `google` |
| `TIERLIST_IMAGE_ENGINE`             | Force `serpent` or `brave` when both keys are set     |


## TCG and Say (env for v1)


| Key                  | Description                                                 |
| -------------------- | ----------------------------------------------------------- |
| `MANA_SYMBOLS`       | JSON object of mana symbol → Discord custom emoji           |
| `WEBHOOK_URL`        | Webhook URL for Say (secret-adjacent)                       |
| `CHARACTER_AVATARS`  | JSON object of character name to avatar URL                 |


MTG autolink channels, birthday/voice channels, error alerts, and reaction emoji strings are configured with `.setup`.

## Guild settings (Postgres / `.setup`)

Schema: `guild_config.settings` + `guild_config.setting_values`.

Admin gate: Discord **Administrator** permission, or any role stored in `bot_admin_role_ids` via `.setup`.

One-shot migration from an old Doppler/env fill: `.setup import-env` (or the Import button) while those keys still exist in the process environment. Then remove guild snowflake keys from Doppler and keep secrets/infra only.

Unset keys soft-disable features (same as the old `0` / `[]` defaults). Use **Skip** on a feature group to mark it intentionally unused.
