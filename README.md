<p align="center">
  <img src="assets/lilith-title.svg" alt="L.I.L.I.T.H." width="520" />
</p>

<p align="center">
  <strong>L</strong>if3 · <strong>I</strong>ntelligence · <strong>L</strong>ogistics · <strong>I</strong>ntegrated · <strong>T</strong>o · <strong>H</strong>elp
</p>

<p align="center">
  <em>A kitchen-sink Discord bot for economy, gaming, utilities, and entertainment.</em>
</p>

<p align="center">
  <a href="docs/QUICKSTART.md">Quick start</a>
  ·
  <a href="#command-reference">Command reference</a>
  ·
  <a href="docs/CONTRIBUTING.md">Contributing</a>
</p>

---

# L.I.L.I.T.H.

HUZZAH! LILITH started as a sandbox to experiment with Discord slash commands and has grown into the bot below. Slash commands are loaded from cogs/production in main_bot.main (plus optional top-level commands registered from MUSIC_FOLDER_* env vars).

This bot targets a single Discord guild; channels, roles, and IDs come from environment variables (see .env.example). To contribute, read docs/CONTRIBUTING.md.

## Docs index

| Document | Topic |
|----------|-------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Setup for published image, local build, bare metal, and VPS |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable |
| [docs/DATABASE.md](docs/DATABASE.md) | PostgreSQL, backup, restore, migration |
| [docs/MUSIC.md](docs/MUSIC.md) | Lavalink and local audio |
| [docs/SCRIPTS.md](docs/SCRIPTS.md) | Operator and maintainer scripts |
| [docs/VPS_DEPLOY.md](docs/VPS_DEPLOY.md) | Remote host and GitHub Actions |
| [docs/BARE_METAL.md](docs/BARE_METAL.md) | Host Python without Docker |
| [docs/SECRETS_DOPPLER.md](docs/SECRETS_DOPPLER.md) | Optional Doppler injection |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Clone, local builds, pull requests |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents (local and Cursor Cloud) |
| [docs/CONVENTIONAL_COMMITS.md](docs/CONVENTIONAL_COMMITS.md) | Optional commit message style |

## Quick start (summary)

Most operators use the published image (no git clone):

1. Install Docker Engine with the Compose plugin.
2. Run `scripts/install.sh` in an empty directory.
3. Set `DISCORD_BOT_TOKEN`, `APPLICATION_ID`, and `GUILD_ID` in `.env`.
4. Leave `DATABASE_URL` empty for the bundled Postgres default.
5. Run `./scripts/bot.sh up`.

Full steps for that path, plus clone-and-build, bare metal, and VPS: [docs/QUICKSTART.md](docs/QUICKSTART.md).

For contribution rules and cog layout, see [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Project layout

```text
Discord-Bot-Sandbox/
├── docker-compose.yml          # Canonical Compose stack (bot, Lavalink, Postgres)
├── Dockerfile
├── .env.example                # Environment template
├── pyproject.toml
├── scripts/
│   ├── install.sh              # Fresh host install
│   ├── bot.sh                  # Operator entry point
│   ├── run_bot.sh              # Host Python runner
│   ├── docker_compose_up.sh    # Local image build + Compose
│   └── …
├── src/main_bot/
│   ├── main.py
│   ├── cogs/production/        # Slash command cogs
│   ├── cogs/development/       # Optional development cogs
│   ├── db/                     # PostgreSQL pool and DDL
│   ├── server_configs/         # Guild config loaders
│   └── utils/                  # Shared helpers
├── lavalink/
│   ├── application.yml.example
│   └── run-local.sh            # Bare-metal Lavalink helper
├── local_audio/                # Music and SFX (gitignored content)
├── logs/                       # Runtime logs (gitignored)
├── admin_tools/                # Database verify and cleanup tools
├── docs/                       # Project documentation
└── tests/
```

---

## Command reference

Channels, roles, and IDs come from environment variables. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

### Table of contents

- [Entertainment and games](#entertainment-and-games)
- [Economy](#economy)
- [Gambling and betting](#gambling-and-betting)
- [Social features](#social-features)
- [Utilities](#utilities)
- [Information](#information)
- [Administration](#administration)
- [Request system](#request-system)
- [Powerups](#powerups)
- [Music and local audio](#music-and-local-audio)
- [More production commands](#more-production-commands)
- [How coins work](#how-coins-work)
- [Permission levels](#permission-levels)
- [Support](#support)

### Entertainment and games

#### `/8ball <question>`

Ask the magic 8-ball a question.

- **Parameters:** `question` (text)

#### `/movie <title>`

Search for movie information with OMDb.

- **Parameters:** `title` (text)

#### `/mtg cardlookup <card_name>`

Look up Magic: The Gathering card information.

- **Parameters:** `card_name` (text)

#### `/roulette`

Play European roulette with betting options.

#### `/divine_personality`

Match a Greek god to your personality through a quiz.

#### `/trivia play` / `/trivia stats` / `/trivia leaderboard`

Play trivia, view your stats, or open the leaderboard.

#### `/wheel`

Create a spinning wheel with 2 to 20 custom values.

#### `/wheelvc [channel]`

Same as `/wheel`, with options from voice channel members.

### Economy

#### `/econ balance [member]`

Check your coin balance or another member balance.

#### `/econ give <member> <amount> [reason]`

Give coins to another user.

#### `/econ request <member> <amount> [reason]`

Request coins from another user.

#### `/econ leaderboard`

Display the server coin leaderboard.

#### `/econ tax <member> <amount> [reason]` (admin)

Remove coins from a user balance. Requires `admin_user_ids`.

### Gambling and betting

#### `/cointoss <choice> <amount>`

Bet on heads or tails.

#### `/blackjack`

Play blackjack against the house.

#### `/wager create <title> <description>`

Create a betting event.

#### `/wager list`

List active wagers.

#### `/wager my_bets`

View your betting history.

#### `/wager history`

View recently finalized wagers.

#### `/wager finalize` (admin)

List wagers that need finalization.

#### `/wager delete <wager_id>` (admin)

Delete a wager.

### Social features

#### `/bday [username]`

Show upcoming birthdays or one member birthday.

#### `/say <character> <message>`

Send a message as a character. Costs 200 coins.

#### `/buzzer`

Start a buzzer session with interactive buttons.

#### `/vote`

Start a multi-option vote.

#### `/bday-all`

List every registered birthday by calendar month.

### Utilities

#### `/voice tidy_up`

Clean up and organize voice channels.

#### `/voice reserve_channel <duration>`

Reserve a voice channel for a number of minutes.

#### `/voice create_temp_channel <name>`

Create a temporary voice channel.

#### `/voice league`

Move the league channel out of the hidden category.

#### `/voice select_channel`

Retrieve a channel from the hidden category.

#### `/watchparty show` / `/watchparty hide`

Move the watch party channel between categories.

#### `/vacate <from> <to>`

Move all users from one voice channel to another.

#### `/brainrot`

Play short sound effects in voice from `local_audio/brainrot/`.

#### `/waterboard <user>`

Move a user through water-themed voice channels. Costs coins.

#### `/enhanced-waterboard <user>`

Waterboard and temporarily hide the user original channel.

#### `/waterboard-party`

Waterboard everyone in your current voice channel except yourself.

#### `/waterboard-ranks`

View waterboarding statistics.

#### `/executivepardon <user> <hours>` (admin)

Grant temporary exemption from waterboarding.

### Information

#### `/pkgo add-friendcode <ign> <friend_code>`

Add a Pokemon GO friend code to the clan roster.

#### `/pkgo friendcode [member]`

Display a member Pokemon GO IGN and friend code.

#### `/pkgo clan-friendcodes`

List all clan Pokemon GO friend codes.

#### `/counter [name] [option1] … [option5]`

Personal counter with increment and decrement controls.

#### `/coc [username]`

Clash of Clans roster lookup.

#### `/pokemon`

Pokemon team and dex helpers (`team-create`, `team-list`, `search`, `info`, and related subcommands).

### Administration

#### `/status set <activity>` / `/status start` / `/status stop`

Set or cycle the bot custom status.

#### `/event create` / `/event list` / `/event edit` / `/event delete`

Manage server events.

#### `/reminder`

Create a reminder for yourself and others.

### Request system

#### `/feature request` / `/feature list` / `/feature resolve` (admin)

Submit and manage feature requests.

#### `/bug report` / `/bug list` / `/bug resolve` (admin)

Submit and manage bug reports.

#### `/admin_toggle` (Discord Administrator)

Enable, disable, list, or reload selected admin-only commands.

### Powerups

Powerups are purchasable features such as cosmetic name colors or waterboard defense.

#### `/powerups purchase` / `/powerups inventory` / `/powerups active`

Browse, buy, and manage powerups.

#### `/powerups art-requests` (restricted)

Art commission requests for configured maintainers.

### Music and local audio

Requires Lavalink. See [docs/MUSIC.md](docs/MUSIC.md).

#### `/music play <query>` / `/music stop`

Stream or search via Lavalink. Stop clears the session.

#### `/gaming`

Play from `local_audio/music/gaming/<game>/`.

Env `MUSIC_FOLDER_1` … `MUSIC_FOLDER_25` register extra slash commands for flat folders under `local_audio/music/`.

### More production commands

#### League of Legends (OP.GG)

- `/opgg_summoner` — recent performance
- `/opgg_matchup` — lane matchup guide
- `/opgg_esports_schedule` — upcoming matches
- `/opgg_standings` — team standings

#### Minecraft (`/crafty`)

Crafty Controller integration: server list, start, stop, restart, status, backup, console, whitelist, and automation. Some commands may be gated by `/admin_toggle`.

### How coins work

Users earn coins from voice activity, text activity, special events, and gambling. Users spend coins on gambling, waterboarding, character messages, powerups, and community wagers.

### Permission levels

- Commands marked **(admin)** require membership in `admin_user_ids` unless noted otherwise.
- `/admin_toggle` requires the Discord Administrator permission.
- Economy commands require a sufficient coin balance where applicable.
- `/event`, `/status`, and `/reminder` rely on Discord integration permissions.

Optional `LOAD_DEVELOPMENT_COGS` loads extensions from `cogs/development/`.

### Support

1. Use `/bug report` for technical problems.
2. Use `/feature request` for new feature ideas.
3. Contact server administrators for urgent matters.
4. Open a GitHub issue for changes to this repository.
