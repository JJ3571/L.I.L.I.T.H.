# Scripts

This document lists operator and maintainer scripts.


| Audience                  | Path                               | Scripts                                                                   |
| ------------------------- | ---------------------------------- | ------------------------------------------------------------------------- |
| Run the published image   | [QUICKSTART.md](QUICKSTART.md)     | `install.sh`, plain `docker compose`, optional `bot.sh`                   |
| Change source and rebuild | [CONTRIBUTING.md](CONTRIBUTING.md) | `docker_compose_up.sh`, `local_docker_build.sh`, `local_docker_deploy.sh` |
| Host Python               | [BARE_METAL.md](BARE_METAL.md)     | `run_bot.sh`                                                              |


## Operator scripts


| Script                           | Purpose                                                   | Image                  |
| -------------------------------- | --------------------------------------------------------- | ---------------------- |
| `scripts/install.sh`             | Download compose files and templates for a fresh host     | N/A (setup only)       |
| `scripts/bot.sh`                 | Start, stop, update, logs, backup, restore, psql, doctor  | Published GHCR image   |
| `scripts/run_bot.sh`             | Run the bot with host Python (`uv`)                       | None (host process)    |
| `scripts/docker_compose_up.sh`   | Local image build and Compose from `.docker-local-build/` | Local Dockerfile build |
| `scripts/local_docker_build.sh`  | Prepare or build the local Docker staging directory       | Local Dockerfile build |
| `scripts/local_docker_deploy.sh` | Recycle the local Docker staging stack                    | Local Dockerfile build |




### `scripts/install.sh`

Creates a deploy directory without a git clone.

```bash
curl -fsSL https://raw.githubusercontent.com/JJ3571/L.I.L.I.T.H./main/scripts/install.sh | bash
```

Environment overrides: `INSTALL_DIR`, `REPO`, `REF`.

### `scripts/bot.sh`

Use after the install script, or from any directory that holds the root `docker-compose.yml` and `.env`. This script runs the published GHCR image. It does not build from source.

```bash
./scripts/bot.sh up
./scripts/bot.sh down
./scripts/bot.sh restart
./scripts/bot.sh update
./scripts/bot.sh logs
./scripts/bot.sh status
./scripts/bot.sh backup
./scripts/bot.sh restore backups/bot-YYYYMMDD-HHMMSS.dump
./scripts/bot.sh psql
./scripts/bot.sh doctor
```

Optional `--dir DIR` selects another compose project directory.

### `scripts/run_bot.sh`

Runs `uv run python -m main_bot`. Default mode is `--env`. Pass `--doppler` for Doppler injection.

```bash
./scripts/run_bot.sh
./scripts/run_bot.sh --doppler
```

Note: `uv` does not load `.env`. Export variables first, or source `.env` in the shell. See [BARE_METAL.md](BARE_METAL.md).

### Local Docker build (clone / contributors)

These scripts build the bot image from the repository `Dockerfile`. Use them when you change source code or custom cogs. See [CONTRIBUTING.md](CONTRIBUTING.md).

1. Run `./scripts/local_docker_build.sh prepare` once (or let `docker_compose_up.sh` do it).
2. Start with `./scripts/docker_compose_up.sh`.
3. Recycle with `./scripts/local_docker_deploy.sh`.

Staging lives in `.docker-local-build/` (gitignored). Default secrets mode is `--env`.

## Database scripts


| Script                                             | Purpose                                     |
| -------------------------------------------------- | ------------------------------------------- |
| `scripts/postgres_dump_and_restore_helpers.py`     | Low-level `pg_dump` / `pg_restore`          |
| `scripts/postgres_migrate_hosted_to_local.sh`      | Copy data between two `DATABASE_URL` values |
| `scripts/migrate_sqlite_files_to_postgres_once.py` | One-time SQLite to Postgres migration       |


See [DATABASE.md](DATABASE.md).

## Maintainer scripts


| Script                   | Purpose                       |
| ------------------------ | ----------------------------- |
| `scripts/tag_release.sh` | Interactive semver tag helper |




## Admin tools

Run these with `uv` from the repository root. They need `DATABASE_URL` in the environment unless noted.


| Tool                                | Purpose                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `admin_tools/verify_databases.py`   | Connect to Postgres, ensure schemas, print row counts, run sanity checks |
| `admin_tools/birthday_cleanup.py`   | Interactive cleanup of invalid birthday rows                             |
| `admin_tools/check_dependencies.py` | Check Python version, imports, and `pyproject.toml` dependencies         |


```bash
DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  uv run python admin_tools/verify_databases.py

uv run python admin_tools/check_dependencies.py
```

Exit code `0` means success. A non-zero exit code means a failed check.