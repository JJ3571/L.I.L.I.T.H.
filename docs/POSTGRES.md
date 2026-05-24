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

### Neon `pg_dump` / `nc`: timeouts on port 5433 but 5432 works

Neon’s **pooled** URL uses host `…-pooler…neon.tech` and port **5433**. The **direct** URL uses host `ep-….neon.tech` (no `-pooler`) and port **5432**. Some VPS or host firewalls allow **5432** but block outbound **5433**.

`pg_dump` must use the **direct** connection with an **explicit** port:

```text
postgresql://USER:PASS@ep-xxx.c-3.us-west-2.aws.neon.tech:5432/neondb?sslmode=require
```

If you only remove `-pooler` from the hostname but leave **`:5433`** from the pooled string, clients still dial 5433 and time out. Check `echo "$PGPORT"` — unset it if it is `5433` before migrating.

Quick test on the VPS:

```bash
nc -vz ep-xxx.c-3.us-west-2.aws.neon.tech 5432    # should succeed
nc -vz ep-xxx-pooler.c-3.us-west-2.aws.neon.tech 5433   # may time out
psql 'postgresql://...@ep-xxx...neon.tech:5432/neondb?sslmode=require' -c 'SELECT 1'
```

Use **Connect → Direct connection** in the Neon console (not Pooled) when copying `SOURCE_DATABASE_URL`.

### `pg_dump`: server version mismatch (client 16, Neon 17)

Neon runs **PostgreSQL 17+**. **`pg_dump` must be the same major version or newer than the server** — Ubuntu’s default `postgresql-client` (16 on 24.04) cannot dump a PG 17 database:

```text
pg_dump: error: aborting because of server version mismatch
```

On the VPS, install **PostgreSQL 17 client tools** (PGDG repo), then re-run the migrate script:

```bash
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh   # accept prompts
sudo apt-get install -y postgresql-client-17
pg_dump --version   # should show 17.x
```

**Restore** also needs `pg_restore` 17+ when loading a dump taken from Neon. After `postgresql-client-17` is installed, both `pg_dump` and `pg_restore` on `PATH` should be 17.

**Without apt:** dump with the repo’s bundled Postgres image, then restore with the script (local target must still be PG 17+):

```bash
DUMP=/tmp/botpg.dump
docker run --rm -v /tmp:/tmp postgres:17-alpine \
  pg_dump -Fc --no-owner --no-acl -f /tmp/botpg.dump \
  'postgresql://...@ep-xxx...neon.tech:5432/neondb?sslmode=require'

DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  uv run python scripts/postgres_dump_and_restore_helpers.py restore \
  --input "$DUMP" --clean --if-exists
```

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
SOURCE_DATABASE_URL='postgresql://...@ep-xxx...neon.tech:5432/neondb?sslmode=require' \
TARGET_DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
./scripts/postgres_migrate_hosted_to_local.sh
```

Stop the bot against the source DB before migrating to avoid dual writers. Reverse direction: swap URLs (Neon target must allow TLS; pool adds `sslmode=require` for non-local hosts when omitted).

## Risks when moving hosts

- **SSL:** Neon expects TLS; bundled/local typically does not. Use the right URL per environment (`sslmode` in URL or hostname rules in `db/pool.py`).
- **Schema drift:** Manual DDL outside `ddl.py` is not recreated on empty DBs; restores preserve whatever was dumped.
- **`pg_dump` in container:** The bot image does not ship PostgreSQL clients; host-side tools or optional Dockerfile changes are needed for `database_backup` / dumps inside the container.
