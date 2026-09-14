# Bare metal

This document describes how to run the bot with host Python and `uv`. Use this path only when you cannot use Docker Compose. There are a few things you'll need to setup manually, as the Docker stack handles the database and lavalink.

 See [QUICKSTART.md](QUICKSTART.md) for other deployment options.

## Requirements

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/)
- A reachable PostgreSQL server
- Optional: Java 21 for a local Lavalink JAR

## Install dependencies

1. Clone the repository.
2. Change to the repository root.
3. Sync dependencies.

```bash
uv sync
```

For tests, add the development group.

```bash
uv sync --group dev
```

## Configure secrets

The application does not load `.env` automatically under `uv`. Export variables in the shell, or load the file before you run the bot.

1. Copy `.env.example` to `.env`.
2. Set `DISCORD_BOT_TOKEN`, `APPLICATION_ID`, and `GUILD_ID`.
3. Set `DATABASE_URL` to a reachable PostgreSQL URL.

```bash
set -a
source .env
set +a
```

Or use the optional Doppler injection:

```bash
./scripts/run_bot.sh --doppler
```



## PostgreSQL for bare metal

You need any PostgreSQL 17-compatible server. Options include:

- The bundled service from the root compose file (`COMPOSE_PROFILES=bundled-db`) while you run only the bot on the host
- An external cloud database

Example local URL when Postgres listens on loopback:

```text
postgresql://bot:bot@127.0.0.1:5432/discord_bot
```

See [DATABASE.md](DATABASE.md).

## Lavalink for bare metal

1. Change to the `lavalink` directory.
2. Copy `application.yml.example` to `application.yml`.
3. Download the official Lavalink server JAR from the Lavalink releases page.
4. Place the JAR in `lavalink/` as `Lavalink.jar`.
5. Set `LAVALINK_URI=http://127.0.0.1:2333` in your environment.
6. Match `LAVALINK_PASSWORD` to `lavalink.server.password` in `application.yml`.
7. Start Lavalink.

```bash
cd lavalink
./run-local.sh
```

On macOS with multiple JDKs, select Java 21 first.

```bash
export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
./run-local.sh
```

See [MUSIC.md](MUSIC.md).

## Run the bot

Default mode uses the current environment (after you export or source `.env`).

```bash
./scripts/run_bot.sh
```

Equivalent explicit flag:

```bash
./scripts/run_bot.sh --env
```



## systemd unit (optional)

Use systemd when you want the host process to restart on boot. Prefer Docker Compose on a VPS when possible. See [VPS_DEPLOY.md](VPS_DEPLOY.md).

Example unit file `/etc/systemd/system/discord_bot.service`:

```ini
[Unit]
Description=Discord bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=discord_bot
WorkingDirectory=/home/discord_bot
EnvironmentFile=/home/discord_bot/.env
ExecStart=/home/discord_bot/scripts/run_bot.sh --env
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

1. Install the unit file.
2. Reload systemd.
3. Enable and start the service.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now discord_bot.service
sudo systemctl status discord_bot.service
```

Optional Lavalink unit (adjust paths):

```ini
[Unit]
Description=Lavalink
After=network-online.target

[Service]
Type=simple
User=discord_bot
WorkingDirectory=/home/discord_bot/lavalink
Environment=JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ExecStart=/home/discord_bot/lavalink/run-local.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```



## Verify

```bash
DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  uv run python admin_tools/verify_databases.py
uv run pytest
```

