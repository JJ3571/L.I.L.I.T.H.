# discord_bot - Command Reference

HUZZAH! This Discord bot started as a sandbox to play around with Discord bot features and slash commands. It has now evolved into a "kitchen sink" bot with economy, gaming, utilities, and entertainment commands. Below is a complete reference of all available slash commands.

This bot targets a single Discord guild; channels, roles, and IDs come from environment variables (see `.env.example`).

---

## Setup & secrets

### Layout you should prepare

These paths matter if you run **Docker Compose** or Lavalink-backed music:

| Path | Purpose |
|------|---------|
| **`lavalink/application.yml`** | Runtime Lavalink config (gitignored). Copy [`lavalink/application.yml.example`](lavalink/application.yml.example) → `lavalink/application.yml` and set `lavalink.server.password` to match **`LAVALINK_PASSWORD`** in your secrets (same value as in `.env.example` / Doppler). |
| **`local_audio/`** | Repo-root folder mounted read-only into the bot container for music/SFX assets (see `docker-compose.yml`). Create it before `docker compose up` if it does not exist; subfolders depend on what your cogs expect (for example under `local_audio/music/`). |

Named Docker volumes (`tierlist_data`, `db_data`) need no manual directories.

### Secrets: Doppler **or** repo-root `.env`

Use either workflow (or mix: Doppler locally and `.env` only on a CI host—whatever fits).

**Option A — [Doppler](https://www.doppler.com/)**

1. Install the [Doppler CLI](https://docs.doppler.com/docs/cli) and link this repo to your project/config (`doppler configure`, or `doppler setup`).
2. **Docker Compose:** either  
   - `./scripts/docker_compose_up.sh` (or a copy at repo root: `./docker_compose_up.sh`) — refreshes `.env` from Doppler then runs `docker compose up --pull always`, or  
   - `doppler run -- docker compose up --pull always` — injects secrets into the Compose process without writing `.env`.
3. **Local Python:** use Python **3.12–3.13** (Nextcord on PyPI does not support 3.14 yet). From repo root: `uv sync`, then `doppler run -- uv run python -m main_bot` or `doppler run -- uv run bot`.

**Option B — Local `.env` file**

1. Copy `.env.example` → `.env` at the **repository root** and fill in values. `.env` is gitignored—never commit real secrets.
2. **Docker Compose:** run `docker compose up` (or `docker compose up --pull always -d`) from the repo root. Compose substitutes `${VAR}` from `.env` into the bot service per [`docker-compose.yml`](docker-compose.yml).
3. **Local `uv run`:** the app does **not** auto-load `.env`; export variables into your shell or IDE, use Option A for development, or rely on Compose when testing in containers.

Cron/systemd on a VPS often wraps the bot with `doppler run -- …` or an equivalent env file—same variables as `.env.example`.

### Published VPS bundle (no Git clone)

Running from **[GHCR](https://docs.github.com/en/packages/getting-started-with-github-container-registry)** only (no repo clone)? Download **`discord-bot-standalone.zip`** from the repo’s **[Releases](https://github.com/jj3571/Discord-Bot-Sandbox/releases)** (built each time you **publish** a GitHub Release) and unpack into **one folder** on the machine. It ships **`docker-compose.yml`**, **`.env.template`**, **`startup_script.sh`**, **`rollout.sh`**, **`lavalink/application.yml.example`**, plus **`README.md`** with the standalone layout explained. Typical upgrade:

```bash
cd /path/to/discord-bot-standalone
chmod +x startup_script.sh rollout.sh
./rollout.sh
```

Developers regenerate the artifact locally anytime with **`./scripts/build_deploy_bundle.sh`** (**`dist/discord-bot-standalone.zip`** plus an unpacked **`dist/discord-bot-standalone/`**). That script copies Compose from root **`docker-compose.yml`** (service definitions unchanged; only comments above **`services:`** are swapped for ZIP readers), **`.env.example` → `.env.template`**, **`lavalink/application.yml.example`**, and **`scripts/deploy_bundle/`** helpers — nothing is duplicated manually in-tree.

---

## 📋 Table of Contents

- [Setup & secrets](#setup--secrets)
- [📁 Project layout](#project-layout)
- [🎮 Entertainment & Games](#-entertainment--games)
- [💰 Economy System](#-economy-system)
- [🏆 Gambling & Betting](#-gambling--betting)
- [🎉 Social Features](#-social-features)
- [🔧 Utilities](#-utilities)
- [📊 Information](#-information)
- [⚙️ Administration](#️-administration)
- [🧪 Testing Commands](#-testing-commands)

---

## 📁 Project layout

Overview of how the repository is organized. Paths marked *optional* or *local* may be missing on a fresh clone or are excluded from version control (see [.gitignore](.gitignore)).

```text
discord_bot/                    # clone URL may still show Discord-Bot-Sandbox until renamed
├── pyproject.toml              # Dependencies (uv); lockfile: uv.lock
├── docker-compose.yml          # Bot + Lavalink; secrets via .env or doppler run
├── Dockerfile                  # Bot image (optional remote image in compose)
├── .env.example                # Env template → copy to repo-root .env (gitignored)
├── main.py                     # Thin entrypoint → main_bot.main.run()
├── opgg_mcp_test.py            # Local MCP / tooling experiment
├── README.md
├── lavalink/
│   └── application.yml.example # Copy to application.yml locally (password ↔ LAVALINK_PASSWORD)
├── admin_tools/                # One-off maintenance & verification scripts
│   ├── README.md
│   ├── birthday_cleanup.py
│   ├── check_dependencies.py
│   ├── db_helper.py
│   ├── file_renamer.py
│   └── verify_databases.py
├── databases/                  # *local* SQLite databases (*.db gitignored)
├── docs/                       # Guides, env key notes, example snippets
├── scripts/
│   ├── build_deploy_bundle.sh  # dist/discord-bot-standalone.zip (+ folder) from canonical compose/.env
│   └── deploy_bundle/          # Sources for standalone ZIP (startup/rollout/README + compose header frag)
├── src/
│   └── main_bot/               # Installable package (uv run python -m main_bot)
│       ├── cogs/
│       │   ├── archived/
│       │   ├── debugging/
│       │   ├── production/
│       │   └── testing/
│       ├── server_configs/
│       └── utils/
└── local_audio/                # *optional* local audio (gitignored): music/jazz|lofi|gaming, brainrot/*.mp3, …
```

**Not shown (typical machine-local):** `.venv/` or other virtualenvs, repo-root `.env`, `lavalink/application.yml` (generated from the example), `nextcord.log`, and IDE folders such as `.vscode/` or `.cursor/` when ignored. Add `databases/*.db` and tracks under `local_audio/music/` (and other `local_audio/` subfolders) as needed when running the bot.

---

## 🎮 Entertainment & Games

### `/8ball <question>`
Ask the magic 8-ball a question and receive a mystical response.
- **Parameters:** `question` (text) - Your question for the 8-ball

### `/movie <title>`
Search for movie information using the OMDB database.
- **Parameters:** `title` (text) - Name of the movie to search for

### `/mtg cardlookup <card_name>`
Look up Magic: The Gathering card information.
- **Parameters:** `card_name` (text) - Name of the MTG card

### `/roulette`
Play an interactive game of European roulette with betting options.

### `/greek-god`
Discover which Greek god matches your personality through an interactive quiz.

---

## 💰 Economy System

### `/econ balance [member]`
Check your coin balance or someone else's balance.
- **Parameters:** `member` (optional) - User to check balance for

### `/econ give <member> <amount> [reason]`
Give coins to another user.
- **Parameters:** 
  - `member` (required) - User to give coins to
  - `amount` (required) - Number of coins to give
  - `reason` (optional) - Reason for the transaction

### `/econ request <member> <amount> [reason]`
Request coins from another user (creates a transaction request).
- **Parameters:**
  - `member` (required) - User to request coins from
  - `amount` (required) - Number of coins to request
  - `reason` (optional) - Reason for the request

### `/econ leaderboard`
Display the server's coin leaderboard showing top earners.

### `/econ tax <member> <amount> [reason]` 🔒
**[Admin Only]** Remove coins from a user's balance.
- **Parameters:**
  - `member` (required) - User to tax
  - `amount` (required) - Number of coins to remove
  - `reason` (optional) - Reason for taxation

---

## 🏆 Gambling & Betting

### `/cointoss <choice> <amount>`
Toss a coin and potentially double your wager!
- **Parameters:**
  - `choice` (required) - Choose "heads" or "tails"
  - `amount` (required) - Coins to bet

### `/blackjack`
Play a game of blackjack against the house.

### `/wager create <title> <description>`
Create a new betting event for other users to wager on.
- **Parameters:**
  - `title` (required) - Title of the wager
  - `description` (required) - Description of what's being wagered

### `/wager list`
View all active wagers available for betting.

### `/wager my_bets`
View your personal betting history (active and past bets).

### `/wager history`
View recently finalized wagers and their outcomes.

### `/wager finalize` 🔒
**[Admin Only]** List wagers that need finalization.

### `/wager delete <wager_id>` 🔒
**[Admin Only]** Delete a wager entirely.

---

## 🎉 Social Features

### `/bday [username]`
Shows upcoming birthdays or view a specific user's birthday.
- **Parameters:** `username` (optional) - User to check birthday for

### `/say <character> <message>`
Send a message as a character using AI. Costs 200 coins.
- **Parameters:**
  - `character` (required) - Character to roleplay as
  - `message` (required) - Message to send

### `/buzzer`
Start a new buzzer session with interactive buttons for quick responses.

---

## 🔧 Utilities

### `/voice tidy_up`
Manually clean up and organize voice channels.

### `/voice reserve_channel <duration>`
Reserve a voice channel for a set amount of time.
- **Parameters:** `duration` (required) - Time to reserve in minutes

### `/voice create_temp_channel <name>`
Create a temporary voice channel with a custom name.
- **Parameters:** `name` (required) - Name for the temporary channel

### `/voice league`
Pull the league channel out of the hidden category.

### `/voice select_channel`
Select a channel to retrieve from the hidden category.

### `/watchparty show`
Move the watch party channel to the visible category.

### `/watchparty hide`
Move the watch party channel to the hidden category.

### `/vacate <from> <to>`
Move all users from one voice channel to another with intelligent rate limiting.
- **Parameters:**
  - `from` (required) - Source voice channel to move users from
  - `to` (required) - Destination voice channel to move users to
- **Features:** Rate limiting, progress tracking, error handling, retry logic

### `/vacate-config <delay>` 🔒
**[Admin Only]** Configure the rate limiting delay for vacate operations.
- **Parameters:** `delay` (required) - Delay in seconds between moves (0.1-5.0)

---

## 📊 Information

### `/pkgo add-friendcode <ign> <friend_code>`
Add your Pokemon GO friend code to the clan roster.
- **Parameters:**
  - `ign` (required) - Your in-game name
  - `friend_code` (required) - Your Pokemon GO friend code

### `/pkgo friendcode [member]`
Display a user's Pokemon GO IGN and friend code.
- **Parameters:** `member` (optional) - User to check friend code for

### `/pkgo clan-friendcodes`
Get a list of all Pokemon GO friend codes for the clan.

### `/counter list`
View various server counters and statistics.

### `/counter increment <counter_name>`
Increment a specific counter by 1.
- **Parameters:** `counter_name` (required) - Name of counter to increment

---

## ⚙️ Administration

### `/status set <activity>`🔒
**[Admin Only]** Set the bot's custom status.
- **Parameters:** `activity` (required) - Status message to display

### `/status start` 🔒
**[Admin Only]** Start cycling through predefined status messages.

### `/status stop` 🔒
**[Admin Only]** Stop cycling through status messages.

### `/event create <title> <date> <time> [description]` 🔒
**[Admin Only]** Create a new server event.
- **Parameters:**
  - `title` (required) - Event title
  - `date` (required) - Event date
  - `time` (required) - Event time
  - `description` (optional) - Event description

### `/event delete <event_id>` 🔒
**[Admin Only]** Delete an event.

### `/event edit <event_id>` 🔒
**[Admin Only]** Edit an existing event.

### `/event list`
List all upcoming events.

---

## 🛠️ Request System

### `/feature request <title> <description>`
Submit a new feature request for the bot.
- **Parameters:**
  - `title` (required) - Feature title
  - `description` (required) - Detailed description

### `/feature list`
List all active feature requests.

### `/feature resolve <request_id>` 🔒
**[Admin Only]** Mark a feature request as resolved.

### `/bug report <title> <description>`
Report a bug in the bot.
- **Parameters:**
  - `title` (required) - Bug title
  - `description` (required) - Bug description

### `/bug list`
List all active bug reports.

### `/bug resolve <bug_id>` 🔒
**[Admin Only]** Mark a bug report as resolved.

---

## 💪 Powerups System
Powerups are hardcoded functions & features that users can buy! Currently, they're limited to cosmetic name color changes (through a discord role) or other cog features (such as a defense against /waterboard).

### `/powerups purchase`
Browse and purchase powerups from the shop using coins.

### `/powerups inventory`
View and use your owned powerups.

### `/powerups active`
View and manage your currently active powerups.

---

## 🧪 Testing Commands

*These commands are available in testing environments and may have experimental features.*

### `/waterboard <user>`
Move a user through water-themed voice channels (costs coins).
- **Parameters:** `user` (required) - User to waterboard

### `/enhanced-waterboard <user>`
Enhanced waterboard that temporarily hides the user's original channel.
- **Parameters:** `user` (required) - User to enhanced waterboard

### `/waterboard-party`
Waterboard everyone in your current voice channel (except yourself).

### `/waterboard-ranks`
View all-time waterboarding statistics and leaderboard.

### `/executivepardon <user> <hours>` 🔒
**[Admin Only]** Grant exemption from waterboarding for a set time.
- **Parameters:**
  - `user` (required) - User to grant pardon to
  - `hours` (required) - Duration of pardon in hours

---

## 🎮 How Coins Work

The bot features a comprehensive economy system where users earn coins through:
- **Voice Activity**: Earn coins for spending time in voice channels
- **Text Activity**: Earn coins for sending messages
- **Special Events**: Movie night participation and other events
- **Gambling**: Win (or lose) coins through various games

Coins can be spent on:
- Gambling games (cointoss, blackjack, roulette)
- Waterboarding other users
- Character roleplay messages
- Powerups and special abilities
- Betting on community wagers

---

## 🔒 Permission Levels

- **🔒 Admin Commands**: Require administrator permissions
- **💰 Economy Commands**: Require sufficient coin balance
- **👥 Social Commands**: Available to all users
- **🧪 Testing Commands**: May be restricted or experimental

---

## 🆘 Support

There are built in /bug and /feature commands that allow server/guild users to make suggestions or flag potential bugs. 
1. Use `/bug report` for technical problems
2. Use `/feature request` for new feature ideas
3. Contact server administrators for urgent matters

* If you have bugs/suggestions for this main branch, please add them to the Github form!*
---

*README last updated: April 2026*
*Project: discord_bot (package `main_bot`, UV-managed)*
