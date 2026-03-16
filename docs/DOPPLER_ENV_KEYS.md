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

## Optional (feature-dependent)

- `GEMINI_API_KEY` (string)
- `ENVIRONMENT` (string: `development` or `production`) used by `is_development_environment()`

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

## TCG / Say (JSON + strings)

- `MANA_SYMBOLS` (JSON object)
- `WEBHOOK_URL` (string)
- `CHARACTER_AVATARS` (JSON object)
- `ZERONI_REACTION_EMOJI` (string)
- `COMMUNITY_NOTES_REACTION_EMOJI` (string)

