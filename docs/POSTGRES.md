# PostgreSQL for this bot

For **how you run the bot** (bare metal vs Docker vs ZIP bundle), **which scripts call Compose**, and **SQLite → Postgres / host ↔ Neon** moves in one place, see **[RUNNING_THE_BOT.md](RUNNING_THE_BOT.md)**.

The bot uses **one PostgreSQL database** with **multiple schemas** (`economy`, `birthday`, `wager`, … — see `server_configs/database_config.py`). Tables are created at startup from `db/ddl.py` (`CREATE TABLE IF NOT EXISTS`); there are no Alembic migrations.

## Choose a setup

| Scenario | What to use |
|----------|-------------|
| **Docker: bot + Lavalink + bundled DB** (default for local ZIP / compose) | Root `docker-compose.yml`, `COMPOSE_PROFILES=bundled-db`, leave `DATABASE_URL` empty in `.env` so Compose injects `postgresql://...@postgres:5432/...?sslmode=disable`. |
| **Docker: external Postgres only** (Neon, RDS, …) | Clear `COMPOSE_PROFILES` (or omit `bundled-db`). Set **`DATABASE_URL`** to your cloud URL **explicitly** — do not leave it empty, or Compose still substitutes the bundled default. |
| **Bare-metal bot** (`scripts/run_bot.sh --env`) | Set **`DATABASE_URL`** to your server. For local Docker Postgres without full stack: `scripts/postgres_local/start.sh`. |

### Compose profiles

| Profile | Service | Typical `COMPOSE_PROFILES` |
|---------|---------|----------------------------|
| `bundled-db` | `postgres:17-alpine` | `bundled-db` (default in `.env.example`) |
| `admin-ui` | pgAdmin → http://127.0.0.1:${PGADMIN_HOST_PORT:-5050} | `bundled-db,admin-ui` |

`bot` and `lavalink` are **not** profile-gated and always run.

Enable pgAdmin:

```bash
# .env
COMPOSE_PROFILES=bundled-db,admin-ui
```

Log into pgAdmin, **Register server** → Host **`postgres`**, port **5432**, database/user/password from `POSTGRES_*`. Browse **Schemas** under the database (most tables are not in `public`).

### Important: external Postgres without bundled-db

If you clear **`COMPOSE_PROFILES`** but **`DATABASE_URL`** stays empty, Compose still passes the **default** URL targeting hostname `postgres`, which will not resolve. Always set a full **`DATABASE_URL`** when `bundled-db` is off.

## Reading `DATABASE_URL` (`bot:bot` is not the container name)

PostgreSQL URLs follow the usual form:

```text
postgresql://USERNAME:PASSWORD@HOST:PORT/DATABASE_NAME
```

Examples in this repo’s docs often use:

```text
postgresql://bot:bot@127.0.0.1:5432/discord_bot
```

| Piece | Meaning |
|-------|--------|
| **`bot`** (before the colon) | Database role **`POSTGRES_USER`** — defaults to **`bot`** in **`.env.example`** and in **`docker-compose.yml`** (`POSTGRES_USER:-bot`). |
| **`bot`** (after the colon, before `@`) | That role’s password **`POSTGRES_PASSWORD`** — same default **`bot`**. |
| **`127.0.0.1`** | Host **from your laptop or VPS shell**: Postgres is published on loopback at **`POSTGRES_HOST_PORT`** (default **5432**). |
| **`postgres`** (when the bot runs **inside** Compose) | **Hostname of the Postgres service** on the Docker network — **not** the DB username. Compose’s default injected URL uses **`@postgres:5432`** so the bot container resolves the database container by **service name**. |
| **`discord_bot`** | Database name **`POSTGRES_DB`** (default **`discord_bot`**). |

The **Discord bot** runs in a **different** container/service (`bot`). Do not confuse that with the **`bot`** database user — the name overlap is only a convention for the default Postgres role.

If you change **`POSTGRES_USER`**, **`POSTGRES_PASSWORD`**, or **`POSTGRES_DB`** in **`.env`**, use those values in **`DATABASE_URL`** and in **`TARGET_DATABASE_URL`** for migrations. Passwords with special characters (`@`, `#`, `:`, etc.) must be **percent-encoded** in the URL.

## Troubleshooting migrations

### `pg_restore`: unrecognized configuration parameter `transaction_timeout`

Neon runs **PostgreSQL 17+**. Custom-format dumps can include `SET transaction_timeout = 0;`, which **PostgreSQL 16 and older reject**. The bundled/local Postgres image in this repo is **17** so `pg_restore` from Neon generally works. If you still use an older Postgres locally, upgrade the server to **17+** or recreate the volume after updating **`docker-compose.yml`**.

### Image version

Bundled and **`scripts/postgres_local`** Postgres use **`postgres:17-alpine`** (major aligned with Neon). Bump **`docker-compose.yml`** and **`scripts/postgres_local/docker-compose.yml`** together when changing versions.

---

## Managing data

- **Desktop tools:** connect to **127.0.0.1** and **POSTGRES_HOST_PORT** (default 5432) when Postgres is published loopback from compose or `postgres_local`.
- **CLI:** `psql "$DATABASE_URL"` or `scripts/postgres_dump_and_restore_helpers.py`.
- **Verify:** `uv run python admin_tools/verify_databases.py`.

### VPS / safety

Postgres and pgAdmin bind to **127.0.0.1** by default. For remote access, prefer **SSH tunnel** (e.g. `ssh -L 5432:127.0.0.1:5432 user@vps`). Publishing `0.0.0.0` without a firewall is discouraged.

## Neon → local (or local → Neon)

Use **`scripts/postgres_migrate_hosted_to_local.sh`** (wrapper around `postgres_dump_and_restore_helpers.py`):

```bash
SOURCE_DATABASE_URL='postgresql://...@...neon.tech/neondb?sslmode=require' \
TARGET_DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
./scripts/postgres_migrate_hosted_to_local.sh
```

Stop the bot against the source DB before migrating to avoid dual writers. Reverse direction: swap URLs (Neon target must allow TLS; pool adds `sslmode=require` for non-local hosts when omitted).

## Risks when moving hosts

- **SSL:** Neon expects TLS; bundled/local typically does not. Use the right URL per environment (`sslmode` in URL or hostname rules in `db/pool.py`).
- **Schema drift:** Manual DDL outside `ddl.py` is not recreated on empty DBs; restores preserve whatever was dumped.
- **`pg_dump` in container:** The bot image does not ship PostgreSQL clients; host-side tools or optional Dockerfile changes are needed for `database_backup` / dumps inside the container.
