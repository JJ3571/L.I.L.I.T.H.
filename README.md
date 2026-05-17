# discord_bot - Command Reference

HUZZAH! This Discord bot started as a sandbox to play around with Discord bot features and slash commands. It has now evolved into a "kitchen sink" bot with economy, gaming, utilities, and entertainment commands. Below is a reference of slash commands loaded from **`cogs/production`** in `main_bot.main` (plus optional top-level commands registered from **`MUSIC_FOLDER_*`** env vars).

This bot targets a single Discord guild; channels, roles, and IDs come from environment variables (see `.env.example`). To contribute, read **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** (optional commit-style reference: **[docs/CONVENTIONAL_COMMITS.md](docs/CONVENTIONAL_COMMITS.md)**).

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
- [🛠️ Request System](#️-request-system)
- [💪 Powerups System](#-powerups-system)
- [🎵 Music & local audio](#-music--local-audio)
- [🧩 More production commands](#-more-production-commands)
- [🎮 How Coins Work](#-how-coins-work)
- [🔒 Permission Levels](#-permission-levels)
- [🆘 Support](#-support)

---

## Setup & secrets

### Layout you should prepare

These paths matter if you run **Docker Compose** or Lavalink-backed music:

| Path | Purpose |
|------|---------|
| **`lavalink/application.yml`** | Runtime Lavalink config (gitignored). Copy [`lavalink/application.yml.example`](lavalink/application.yml.example) → `lavalink/application.yml`. **`LAVALINK_PASSWORD`** must match your secrets and interpolates into `lavalink.server.password`; for Docker, **`YOUTUBE_OAUTH_ENABLED`** / **`YOUTUBE_OAUTH_REFRESH_TOKEN`** (optional) are passed on the **`lavalink`** service and map to YouTube OAuth in the example YAML. See [`docs/DOPPLER_ENV_KEYS.md`](docs/DOPPLER_ENV_KEYS.md) and [`lavalink/README.txt`](lavalink/README.txt). |
| **`local_audio/`** | Repo-root folder mounted read-only into the bot container for music/SFX assets (see `docker-compose.yml`). Create it before `docker compose up` if it does not exist; subfolders depend on what your cogs expect (for example under `local_audio/music/`). The local-image helper (below) uses **`.docker-local-compose-test/local_audio/`** in its staging tree—do not confuse with a differently spelled path. |
| **`logs/`** | Bind-mounted **`./logs`** on the host: the bot writes **`discord_bot.log`** under **`/app/logs`**; the same folder is mounted for Lavalink (**`./logs:/opt/Lavalink/logs`**) so **`lavalink.log`** (see **`logging.file.name`** in `lavalink/application.yml`) appears beside the bot log (single directory, gitignored). Create **`logs/`** before **`docker compose up`** if Compose does not create it automatically. |

**Local music layout:** Optional env **`MUSIC_FOLDER_1`** … **`MUSIC_FOLDER_25`** register flat folders `local_audio/music/<name>` as slash commands `/<name>` (see `.env.example`). Use **`MUSIC_n_SHUFFLE_START=true`** for random seek-in-track; omit or `false` to play each file from the start (queue order is still shuffled on start). **`/gaming`** always uses `local_audio/music/gaming/<game>/` (audio files per game folder). Up to **25** game folders with audio; cover art: optional `cover.png` / `cover.jpg` next to tracks (or one shared `cover.*` under `gaming/`). Names **`gaming`** and **`brainrot`** cannot be used as `MUSIC_FOLDER_*` values.

Named Docker volumes (`tierlist_data`, `db_data`) need no manual directories.

Docker **`stdout`** (when **`APP_LOG_STDOUT_MIRROR`** is on) plus **`logs/discord_bot.log`** record startup lines **`[BOT_STARTING] …`** — look for **`Loaded extension:`** vs **`FAILED to load extension`**, **`Music cog registered`** vs missing, and **`[music]`** HTTP bind messages. Tune **`NEXTCORD_FILE_LOG_LEVEL`** so **`/logging`** file tails stay readable (**`INFO`** default; **`DEBUG`** embeds Discord gateway noise). Set **`APP_LOG_STDOUT_MIRROR=false`** to keep **`docker compose logs`** quiet while still tailing the file on disk.

### Secrets: Doppler **or** repo-root `.env`

Use either workflow (or mix: Doppler locally and `.env` only on a CI host—whatever fits).

**Option A — [Doppler](https://www.doppler.com/)**

1. Install the [Doppler CLI](https://docs.doppler.com/docs/cli) and link this repo to your project/config (`doppler configure`, or `doppler setup`).
2. **Docker Compose:** either  
   - `./scripts/docker_compose_up.sh` (or a copy at repo root: `./docker_compose_up.sh`) — same as `doppler run -- docker compose up --pull always` (secrets in the Compose process; no need for a plaintext `.env` from `doppler secrets download`), or  
   - `doppler run -- docker compose up --pull always` — same injection, run manually.
   - **Local image smoke test (build Dockerfile + Compose):** `./scripts/docker_compose_local_image_test.sh` (default `up --build`) materializes **`.docker-local-compose-test/`** with compose files, Lavalink config, and `local_audio/`, then builds the bot from this repo. Run with secrets the same way as normal Compose, e.g. **`doppler run -- ./scripts/docker_compose_local_image_test.sh`** or a filled staging **`.docker-local-compose-test/.env`**. The script refuses to call Docker if the daemon is not running (avoids long compose noise). `prepare` subcommand only syncs files and does not need Docker.
3. **Local Python:** use Python **3.12–3.13** (Nextcord on PyPI does not support 3.14 yet). From repo root: `uv sync`, then `doppler run -- uv run python -m main_bot` or `doppler run -- uv run bot`.

**Option B — Local `.env` file**

1. Copy `.env.example` → `.env` at the **repository root** and fill in values. `.env` is gitignored—never commit real secrets.
2. **Docker Compose:** run `docker compose up` (or `docker compose up --pull always -d`) from the repo root. Compose substitutes `${VAR}` from `.env` into the bot service per [`docker-compose.yml`](docker-compose.yml).
3. **Local `uv run`:** the app does **not** auto-load `.env`; export variables into your shell or IDE, use Option A for development, or rely on Compose when testing in containers.

Cron/systemd on a VPS often wraps the bot with `doppler run -- …` or an equivalent env file—same variables as `.env.example`.

### Published VPS bundle (no Git clone)

Running from **[GHCR](https://docs.github.com/en/packages/getting-started-with-github-container-registry)** only (no repo clone)? Download **`discord-bot-standalone.zip`** from the repo’s **[Releases](https://github.com/jj3571/Discord-Bot-Sandbox/releases)** (built each time you **publish** a GitHub Release) and unpack into **one folder** on the machine. It ships **`docker-compose.yml`**, **`.env.template`**, **`startup_script.sh`**, **`docker_deploy.sh`**, **`lavalink/application.yml.example`**, plus **`README.md`** with the standalone layout explained. **`startup_script.sh`** / **`docker_deploy.sh`** mirror **`scripts/run_bot.sh`** flags: **`--doppler`** (default; Doppler → `.env` then Compose), **`--env`** (Compose only with an existing **`.env`**), optional **`--dir`** / **`-C`**. Typical upgrade:

```bash
cd /path/to/discord-bot-standalone
chmod +x startup_script.sh docker_deploy.sh
./docker_deploy.sh
```

Developers regenerate the artifact locally anytime with **`./scripts/build_deploy_bundle.sh`** (**`dist/discord-bot-standalone.zip`** plus an unpacked **`dist/discord-bot-standalone/`**). That script copies Compose from root **`docker-compose.yml`** (service definitions unchanged; only comments above **`services:`** are swapped for ZIP readers), **`.env.example` → `.env.template`**, **`lavalink/application.yml.example`**, and **`scripts/deploy_bundle/`** helpers — nothing is duplicated manually in-tree.

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
│   └── application.yml.example # Copy to application.yml locally (LAVALINK_PASSWORD, YOUTUBE_OAUTH_* via Spring placeholders)
├── admin_tools/                # One-off maintenance & verification scripts
│   ├── README.md
│   ├── birthday_cleanup.py
│   ├── check_dependencies.py
│   ├── db_helper.py
│   ├── file_renamer.py
│   └── verify_databases.py
├── databases/                  # *local* SQLite databases (*.db gitignored)
├── docs/
│   ├── CONTRIBUTING.md         # PR flow, releases, env/cog expectations
│   ├── CONVENTIONAL_COMMITS.md # Optional commit-message style + examples
│   ├── DOPPLER_ENV_KEYS.md     # Env reference for Doppler / Compose
│   ├── DEPLOY_DROPLET.md       # VPS / SSH deploy walkthrough
│   └── coghelp/                # Admin command toggle docs + example snippet
├── scripts/
│   ├── build_deploy_bundle.sh  # dist/discord-bot-standalone.zip (+ folder) from canonical compose/.env
│   ├── deploy_bundle/          # Sources for standalone ZIP (startup/docker_deploy/README + compose header frag)
│   ├── docker_compose_up.sh     # doppler run + docker compose (supports repo root vs scripts/)
│   ├── docker_compose_local_image_test.sh  # staging dir + build bot image + compose (see Setup & secrets)
│   ├── deploy.sh                # clone layout: compose down + compose up with pull
│   └── run_bot.sh               # uv run python -m main_bot (--doppler | --env), optional --dir
├── src/
│   └── main_bot/               # Installable package (uv run python -m main_bot)
│       ├── cogs/
│       │   ├── archived/
│       │   ├── debugging/
│       │   ├── production/
│       │   └── testing/
│       ├── server_configs/
│       └── utils/
└── local_audio/                # *optional* local audio (gitignored): music/ + env-driven folder names, music/gaming/<game>/, brainrot/*.mp3, …
```

**Not shown (typical machine-local):** `.venv/` or other virtualenvs, repo-root `.env`, `lavalink/application.yml` (generated from the example), contents of **`logs/`** (runtime log files; directory may be created by you or Compose), and IDE folders such as `.vscode/` or `.cursor/` when ignored. Add `databases/*.db` and tracks under `local_audio/music/` (and other `local_audio/` subfolders) as needed when running the bot.

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

### `/divine_personality`
Discover which Greek god matches your personality through an interactive quiz.

### `/trivia play` / `/trivia stats` / `/trivia leaderboard`
Play trivia, view your stats, or open the trivia leaderboard.

### `/wheel`
Create a spinning wheel with 2–20 custom values (interactive setup).

### `/wheelvc [channel]`
Same as `/wheel`, but options are members of a voice channel (defaults to your current VC).

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
**[Bot admins — `admin_user_ids`]** Remove coins from a user's balance.
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
**[Bot admins — `admin_user_ids`]** List wagers that need finalization.

### `/wager delete <wager_id>` 🔒
**[Bot admins — `admin_user_ids`]** Delete a wager entirely.

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

### `/vote`
Start a vote for multiple options (interactive setup).

### `/bday-all`
List every registered birthday grouped by calendar month (server-wide).

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

### `/brainrot`
Play random short SFX in voice (silence-breaker; uses `local_audio` brainrot assets).

### Waterboarding (voice, costs coins)

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
**[Bot admins — `admin_user_ids`]** Grant exemption from waterboarding for a set time.
- **Parameters:**
  - `user` (required) - User to grant pardon to
  - `hours` (required) - Duration of pardon in hours

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

### `/counter [category]`
Personal counter with category label; use the message buttons to increment, decrement, or reset.

### `/multicounter <name> <option1> <option2> [option3] [option4] [option5]`
Multi-option counter (2–5 labels); track several tallies at once with buttons.

### `/coc [username]`
Clash of Clans roster: look up one member’s linked accounts, or list the whole clan when `username` is omitted. Adding/editing uses interactive flows (admins or self).

### `/pokemon` (team building)
Parent command for Pokémon team and dex helpers, including `team-create`, `team-list`, `team-view`, `team-add`, `team-remove`, `team-delete`, `team-add-menu`, `search`, and `info`.

---

## ⚙️ Administration

### `/status set <activity>`
Set the bot's custom status (stops automatic status rotation).
- **Parameters:** `activity` (required) - Status message to display

### `/status start`
Start cycling through predefined status messages.

### `/status stop`
Stop cycling through predefined status messages.

*(No permission checks in code—narrow who can invoke these via Discord integrations / overrides if needed.)*

### `/event create`
Create a new server event (opens as a Discord modal).

### `/reminder`
Create a reminder for yourself and others (opens as a Discord modal).

### `/event delete <event_id>`
Delete an event.

### `/event edit <event_id>`
Edit an existing event.

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
**[Bot admins — `admin_user_ids`]** Mark a feature request as resolved.

### `/bug report <title> <description>`
Report a bug in the bot.
- **Parameters:**
  - `title` (required) - Bug title
  - `description` (required) - Bug description

### `/bug list`
List all active bug reports.

### `/bug resolve <bug_id>` 🔒
**[Bot admins — `admin_user_ids`]** Mark a bug report as resolved.

### `/admin_toggle` 🔒
**[Discord Administrator]** Enable, disable, list, or reload visibility of selected admin-only commands (e.g. Crafty automation).

---

## 💪 Powerups System
Powerups are hardcoded functions & features that users can buy! Currently, they're limited to cosmetic name color changes (through a discord role) or other cog features (such as a defense against /waterboard).

### `/powerups purchase`
Browse and purchase powerups from the shop using coins.

### `/powerups inventory`
View and use your owned powerups.

### `/powerups active`
View and manage your currently active powerups.

### `/powerups art-requests` (restricted)
Art commission requests (enabled only for configured maintainer(s) in code).

---

## 🎵 Music & local audio

Requires Lavalink (see [Setup & secrets](#setup--secrets)).

### `/music play <query> [search_kind] [songs]`
Stream or search via Lavalink (YouTube Music source); join a voice channel first. If Lavalink rejects the query, check **`lavalink-1`** logs (YouTube OAuth / plugin issues show there). For OAuth, enable **`YOUTUBE_OAUTH_ENABLED`** for the Lavalink container and complete the device flow once, then stash **`YOUTUBE_OAUTH_REFRESH_TOKEN`** in secrets (see `.env.example` / [`docs/DOPPLER_ENV_KEYS.md`](docs/DOPPLER_ENV_KEYS.md)).

### `/music stop`
Disconnect the bot from voice and clear the session.

### `/gaming`
Play through game-specific folders under `local_audio/music/gaming/<game>/` (see env section above).

Env **`MUSIC_FOLDER_1`** … **`MUSIC_FOLDER_25`** register extra top-level slash commands named **`/<folder>`** (e.g. `/jazz`, `/lofi`) for **`local_audio/music/<folder>/`**. Folder names come **only from these env vars**—dropping MP3s into `local_audio/music/jazz/` does **not** create `/jazz` until **`MUSIC_FOLDER_n=jazz`** (and similar for `lofi`). Restart the bot after env changes.

**Docker Compose (two containers):** Lavalink fetches tracks over HTTP using **`MUSIC_LOCAL_HTTP_HOST`** in URLs; aiohttp listens on **`MUSIC_LOCAL_HTTP_BIND_HOST`** (same as host when unset). The **`docker_compose_local_image_test.sh`** override pins **`hostname: bot`** plus `MUSIC_LOCAL_HTTP_HOST=bot` and **`MUSIC_LOCAL_HTTP_BIND_HOST=0.0.0.0`** for you. Root **`docker-compose.yml`** interpolates sane defaults (`bot` / `0.0.0.0` / `8765`) for those three when unset — override in `.env`/Doppler if your deployment differs.

**Doppler alone is not enough for folder slots:** each `MUSIC_FOLDER_n` / `MUSIC_n_SHUFFLE_START` pair must appear under **`bot.environment`** in **`docker-compose.yml`** (the checkout ships pairs for slots **1–3**; copy that pattern through **25** when you need more — Compose never injects arbitrary secrets). Recreate **`bot`** after changes.

---

## 🧩 More production commands

### League of Legends (OP.GG)
- `/opgg_summoner` — recent performance for a summoner  
- `/opgg_matchup` — lane matchup guide  
- `/opgg_esports_schedule` — upcoming esports matches  
- `/opgg_standings` — team standings  

### Minecraft (`/crafty`)
Parent command for Crafty-controller integration: server list, start/stop/restart, status, backup, console command (admin), whitelist add/remove/list, whitelist apply workflow, automation settings (may be gated by `/admin_toggle`).

Optional root commands **`/crafty_automation`** and **`/crafty_automation_status`** may also register when that integration is enabled (same gating behavior as subcommands wired through conditional registration).

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

- **🔒** In this readme usually means **`admin_user_ids`** in server config (`main_bot.server_configs.config`), unless the command explicitly requires Discord’s **Administrator** permission (e.g. `/admin_toggle`).
- **💰 Economy Commands**: Require sufficient coin balance (where applicable).
- **`/event`**, **`/status`**, and **`/reminder`** are **not** extra-gated in code beyond who can invoke the slash in Discord—tighten exposure via integrations if you need that.

Optional **`LOAD_DEVELOPMENT_COGS`** (see `main_bot.main`) loads extra extensions from `cogs/development/` (not listed here unless you enable it).

---

## 🆘 Support

There are built in /bug and /feature commands that allow server/guild users to make suggestions or flag potential bugs. 
1. Use `/bug report` for technical problems
2. Use `/feature request` for new feature ideas
3. Contact server administrators for urgent matters

If you have bugs/suggestions for this main branch, please add them to the Github form!

---

*README last updated: May 2026*
*Project: discord_bot (package `main_bot`, UV-managed)*
