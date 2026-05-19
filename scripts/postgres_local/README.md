# Local Postgres (Docker only)

Small **`postgres:17-alpine`** stack for running the bot **on the host** with `./scripts/run_bot.sh --env`, without bringing up the full **bot + Lavalink** compose file.

## Requirements

- Docker
- Repo-root `.env` (optional) — if present, `POSTGRES_*` from it are applied when you run `start.sh`

## Commands

From the repository root:

```bash
chmod +x scripts/postgres_local/*.sh   # once
./scripts/postgres_local/start.sh
./scripts/postgres_local/status.sh
./scripts/postgres_local/stop.sh        # stops container; volume retains data
```

Default URL (matches `.env.example`):

```bash
export DATABASE_URL=postgresql://bot:bot@127.0.0.1:5432/discord_bot
./scripts/run_bot.sh --env
```

Change port with `POSTGRES_HOST_PORT` in `.env` (same variable as full-stack compose).

For **bot + Lavalink in Docker** with bundled Postgres, use the root **`docker-compose.yml`** and **`COMPOSE_PROFILES=bundled-db`** instead — see [docs/POSTGRES.md](../../docs/POSTGRES.md).
