# Database

The bot uses one PostgreSQL database with multiple schemas. Schema names include `economy`, `birthday`, and `wager`. See `src/main_bot/server_configs/database_config.py`.

Tables are created at startup from `src/main_bot/db/ddl.py` with `CREATE TABLE IF NOT EXISTS`. (This project does NOT use Alembic migrations.)

For the default Docker deploy path, see [QUICKSTART.md](QUICKSTART.md).

## Default setup — bundled Postgres

The root `docker-compose.yml` includes a `postgres:17-alpine` service. The profile name is `bundled-db`.

1. Keep `COMPOSE_PROFILES=bundled-db` in `.env`.
2. Leave `DATABASE_URL` empty.
3. Start the stack with `./scripts/bot.sh up`.

Compose then injects a URL that targets hostname `postgres` on the Docker network.


| Profile      | Service              | Example `COMPOSE_PROFILES` |
| ------------ | -------------------- | -------------------------- |
| `bundled-db` | `postgres:17-alpine` | `bundled-db`               |
| `admin-ui`   | pgAdmin              | `bundled-db,admin-ui`      |


The `bot` and `lavalink` services always run. They are not gated by a profile. Profiles are really here to allow the end user a BYODB option. 

### Enable pgAdmin

1. Set `COMPOSE_PROFILES=bundled-db,admin-ui` in `.env`.
2. Restart the stack.
3. Open `http://127.0.0.1:5050` (or your `PGADMIN_HOST_PORT`).
4. Register a server. Use host `postgres`, port `5432`, and the `POSTGRES_*` credentials.

Most tables live under named schemas, not under `public`.

## External Postgres

If you use Neon, RDS, or another host, complete these steps.

1. Clear `COMPOSE_PROFILES` (leave it empty).
2. Set `DATABASE_URL` to your full PostgreSQL URL.
3. Restart the stack.

CAUTION: If you clear `COMPOSE_PROFILES` but leave `DATABASE_URL` empty, Compose still substitutes the bundled default. The bot then fails to resolve hostname `postgres`.

Example external URL:

```text
postgresql://user:password@db.example.com:5432/neondb?sslmode=require
```



## Reading `DATABASE_URL`

PostgreSQL URLs use this form:

```text
postgresql://USERNAME:PASSWORD@HOST:PORT/DATABASE_NAME
```

Example for host-side tools against the bundled database:

```text
postgresql://bot:bot@127.0.0.1:5432/discord_bot
```


| Piece         | Meaning                                                |
| ------------- | ------------------------------------------------------ |
| First `bot`   | Database role (`POSTGRES_USER`)                        |
| Second `bot`  | Password (`POSTGRES_PASSWORD`)                         |
| `127.0.0.1`   | Host from your laptop or VPS shell                     |
| `postgres`    | Hostname of the Postgres service on the Docker network |
| `discord_bot` | Database name (`POSTGRES_DB`)                          |


The Discord bot runs in the `bot` service. That name is not the database role. The overlap is only a naming convention.

If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB`, update every URL that uses those values. Percent-encode special characters in passwords.

## Backup and restore

Use the operator script from the compose directory.

```bash
./scripts/bot.sh backup
./scripts/bot.sh restore backups/bot-YYYYMMDD-HHMMSS.dump
```

You can also call the Python helpers with `DATABASE_URL` set.

```bash
DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  uv run python scripts/postgres_dump_and_restore_helpers.py dump --output /tmp/bot.dump

DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  uv run python scripts/postgres_dump_and_restore_helpers.py restore --input /tmp/bot.dump --clean --if-exists
```

Verify schemas after a restore.

```bash
DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  uv run python admin_tools/verify_databases.py
```

Open a SQL shell against the bundled database.

```bash
./scripts/bot.sh psql
```



## Move data between hosts

Stop every bot process that writes to the source database before you migrate. Dual writers can corrupt data.

### Hosted database to local or bundled Postgres

```bash
SOURCE_DATABASE_URL='postgresql://...@host:5432/dbname?sslmode=require' \
TARGET_DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  ./scripts/postgres_migrate_hosted_to_local.sh
```

For a host-side restore, use `127.0.0.1` and the mapped port. Do not use hostname `postgres` from outside Compose.

### Local Postgres to a hosted database

Swap the URLs in the same script. The hosted target must allow TLS.

1. Dump from local.
2. Restore to the hosted URL.
3. Set `DATABASE_URL` in `.env` to the hosted URL.
4. Clear `COMPOSE_PROFILES` so the bundled service does not run.
5. Verify with `admin_tools/verify_databases.py`.



### Legacy SQLite to PostgreSQL

Runtime today is PostgreSQL only. Legacy `databases/*.db` files are not used by the running bot.

1. Provision Postgres and set `DATABASE_URL`.
2. Start the bot once so `init_all_schemas` creates tables.
3. Run the one-time migration script.

```bash
uv run python scripts/migrate_sqlite_files_to_postgres_once.py --dry-run
uv run python scripts/migrate_sqlite_files_to_postgres_once.py
```

Use a staging database first. Do not paste production URLs into public channels.

## Troubleshooting hosted dumps



### Port 5433 times out

Some cloud providers publish a pooled URL on port 5433 and a direct URL on port 5432. Prefer the direct connection for `pg_dump`.

```bash
nc -vz ep-xxx.region.aws.neon.tech 5432
psql 'postgresql://...@ep-xxx.region.aws.neon.tech:5432/neondb?sslmode=require' -c 'SELECT 1'
```



### Client version mismatch

`pg_dump` must match or exceed the server major version. A PostgreSQL 17 server needs PostgreSQL 17 client tools.

```bash
pg_dump --version
```

Without host clients, dump from a container.

```bash
docker run --rm -v /tmp:/tmp postgres:17-alpine \
  pg_dump -Fc --no-owner --no-acl -f /tmp/botpg.dump \
  'postgresql://...@host:5432/dbname?sslmode=require'
```



### `transaction_timeout` on restore

Dumps from PostgreSQL 17 can set `transaction_timeout`. Older servers reject that setting. This repo uses `postgres:17-alpine` for the bundled service.

## Safety

Postgres and pgAdmin bind to `127.0.0.1` by default. For remote access, prefer an SSH tunnel.

```bash
ssh -L 5432:127.0.0.1:5432 user@vps
```

CAUTION: Do not publish Postgres on `0.0.0.0` without a firewall. That exposure can leak data.