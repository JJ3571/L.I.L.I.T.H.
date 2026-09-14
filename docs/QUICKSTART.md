# Quick start

There are a few different ways to copy and run the bot, though the majority of people should use Option A:


|                                                       | Who it is for                                                                              | Image source        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------- |
| [Option A](#option-a--install-script-published-image) | 95% of people. Uses Docker Compose. Very easy.                                             | Github Docker image |
| [Option B](#option-b--clone-and-build-a-local-image)  | People looking to contribute to the repo, write custom cogs, or make local changes.        | Local Docker image  |
| [Bare metal](#bare-metal-host-python)                 | People who do not want to use Docker (for whatever reason). Runs using Python on the host. | N/A                 |
| [VPS deploy](#vps-deploy)                             | People who want the bot running on a VPS (with some simple CI deployment options).         | Github Docker image |


Everything besides the Bare Metal option will need Docker Compose installed. A Discord bot token, application ID, and guild ID are always required.

---



## Option A — Install Script

The recommended path for most people. No need to clone the repo.

### 1. Install files

1. Navigate to where you want the discord-bot folder.
2. Run the install script from that directory.

```bash
mkdir -p ~/discord-bot && cd ~/discord-bot
curl -fsSL https://raw.githubusercontent.com/JJ3571/L.I.L.I.T.H./main/scripts/install.sh | bash
```

The script downloads `docker-compose.yml`, `.env.example`, `scripts/bot.sh`, and the Lavalink config template. It also creates `logs/` and `local_audio/`. (It copies `.env.example` to `.env` when `.env` is missing.)

### 2. Configure secrets

1. Open `.env` in a text editor.
2. Set `DISCORD_BOT_TOKEN` to your bot token.
3. Set `APPLICATION_ID` to your Discord application ID.
4. Set `GUILD_ID` to your Discord server ID.

See [SECRETS_DOPPLER.md for info](SECRETS_DOPPLER.md) 

Unless you're bringing your own PostgreSQL database, leave `DATABASE_URL` empty and leave `COMPOSE_PROFILES=bundled-db` as is. There is a bundled PostgreSQL service by default.

If you are using an external database, clear `COMPOSE_PROFILES` and set your `DATABASE_URL`. (See [DATABASE.md](DATABASE.md).)

### 3. Start the bot

```bash
./scripts/bot.sh doctor
./scripts/bot.sh up
./scripts/bot.sh status
./scripts/bot.sh logs
```

Normal Docker Compose commands still work, but a simple /bot.sh wrapper script is included.[b](http://bot.sh)

See [SCRIPTS.md](SCRIPTS.md) for every `bot.sh` subcommand.

---



## Option B — clone and build a local image

Use this when you clone the repository and want Compose to build the bot from the local `Dockerfile`. This route is for people looking to create custom cogs, edit existing cogs, or contribute to the repo.

(For pull requests, cog layout, and review expectations, see [CONTRIBUTING.md](CONTRIBUTING.md).)

### 1. Clone and prepare files

1. Clone the repository.
2. Navigate to the repository root.
3. Copy the environment/Lavalink templates, and create runtime directories.

```bash
cp .env.example .env
cp lavalink/application.yml.example lavalink/application.yml
mkdir -p logs local_audio/music
```



### 2. Configure secrets

Set the three required keys in `.env`:

- `DISCORD_BOT_TOKEN`
- `APPLICATION_ID`
- `GUILD_ID`

Leave `DATABASE_URL` empty with `COMPOSE_PROFILES=bundled-db` for the bundled database.

### 3. Build and start

```bash
./scripts/docker_compose_up.sh
```

That command prepares `.docker-local-build/` if needed, builds the bot image from this repository, and starts the stack. Default secrets mode is `--env`.

### Daily operations (Option B)


| Task                   | Command                                         |
| ---------------------- | ----------------------------------------------- |
| Start or rebuild       | `./scripts/docker_compose_up.sh`                |
| Follow bot logs        | `./scripts/docker_compose_up.sh logs -f bot`    |
| Full recycle           | `./scripts/local_docker_deploy.sh`              |
| Prepare staging only   | `./scripts/local_docker_build.sh prepare`       |
| Prepare and build only | `./scripts/local_docker_build.sh prepare-build` |


Note: `scripts/bot.sh` is still available, but it targets the Docker image from Github. Local buiilds must use the above commands. 

---



## Bare metal (host Python)

Use this option only when you cannot use Docker Compose. (For a while, this was the primary way I ran the bot. It works fine but Docker has many advantages.)

Full detail: [BARE_METAL.md](BARE_METAL.md).

1. Clone the repository.
2. Install [uv](https://docs.astral.sh/uv/).
3. Sync dependencies with `uv sync`.
4. Copy `.env.example` to `.env` and set the required keys.
5. Set `DATABASE_URL` to a reachable PostgreSQL URL.
6. Optional: start Lavalink with `lavalink/run-local.sh`.
7. Load `.env` into the shell, then run the bot.

```bash
uv sync
cp .env.example .env
# Edit .env, then:
set -a && source .env && set +a
./scripts/run_bot.sh
```

---



## VPS deploy

Use this option for a remote Linux host. It's essentially Option A with extra steps.

Full detail: [VPS_DEPLOY.md](VPS_DEPLOY.md).

1. Install Docker Engine and the Compose plugin on the host.
2. You'll still want to use the Option A install script in the deploy directory.
3. Set the three required secrets in `.env`.
4. Start with `./scripts/bot.sh up`.
5. Optional: configure GitHub Actions secrets and variables so `deploy.yml` can SSH and recreate the stack after a release.

```bash
mkdir -p /home/discord_bot && cd /home/discord_bot
curl -fsSL https://raw.githubusercontent.com/JJ3571/L.I.L.I.T.H./main/scripts/install.sh | bash
# Edit .env, then:
./scripts/bot.sh up
```

---



## Related Docs

- [CONFIGURATION.md](CONFIGURATION.md) — every environment variable
- [DATABASE.md](DATABASE.md) — Postgres profiles, backup, and migration
- [MUSIC.md](MUSIC.md) — Lavalink and local audio
- [SCRIPTS.md](SCRIPTS.md) — all operator and maintainer scripts
- [CONTRIBUTING.md](CONTRIBUTING.md) — clone workflows, cogs, and pull requests
- [SECRETS_DOPPLER.md](SECRETS_DOPPLER.md) — optional Doppler injection

