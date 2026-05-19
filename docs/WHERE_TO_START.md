# Running the Discord bot

This guide ties together **how you run the bot** (bare metal vs Docker), **which scripts to use**, and **how to move between databases**. For Postgres-only details (profiles, URLs, pgAdmin), see **[POSTGRES.md](POSTGRES.md)**. For every env variable, see **[DOPPLER_ENV_KEYS.md](DOPPLER_ENV_KEYS.md)**.

---

## Pick a topology

| You want… | Typical layout | Primary entrypoints |
|-----------|----------------|---------------------|
| Python on the host (no bot container) | Clone repo, `uv sync`, Lavalink optional on host | **`scripts/run_bot.sh`** (`--doppler` or `--env`) |
| Bot **built from source** in Docker + Lavalink (+ optional bundled Postgres) | Clone repo; Compose uses **`.docker-local-build/`** staging | **`scripts/docker_compose_up.sh`**, **`scripts/local_docker_deploy.sh`** |
| **Published image** only (no clone) — VPS bundle | One folder with ZIP contents + **`docker-compose.yml`** | **`startup_script.sh`**, **`docker_deploy.sh`** (from the bundle) |

All Docker workflows need the same **secrets** (`DISCORD_BOT_TOKEN`, `DATABASE_URL` / compose defaults, etc.) and the same **paths next to compose**: **`local_audio/`**, **`lavalink/application.yml`**, **`logs/`** (see root **[README.md](../README.md)** — Setup & secrets).

---

## Bare metal (host Python)

1. **Install:** [uv](https://docs.astral.sh/uv/), Python **3.12–3.13**, repo deps: `uv sync` (add `--group dev` for tests).
2. **Secrets:** Export env vars yourself, or use Doppler with **`./scripts/run_bot.sh --doppler`**. The app does **not** auto-load repo **`.env`**; use Doppler or `set -a && source .env && set +a` before **`--env`** if you keep secrets in a file.
3. **Postgres:** Set **`DATABASE_URL`** to any reachable PostgreSQL. Optional local DB in Docker without the full stack: **`scripts/postgres_local/start.sh`** (see **`scripts/postgres_local/README.md`**).
4. **Lavalink:** For music, run Lavalink separately (e.g. **`lavalink/run-local.sh`** or your own JVM setup) and set **`LAVALINK_URI`** (often `http://127.0.0.1:2333`).

```bash
./scripts/run_bot.sh --doppler
# or (secrets already in the environment):
./scripts/run_bot.sh --env
```

Optional **`--dir DIR`** / **`-C DIR`** sets the working directory (default: repo root).

---

## Clone + Docker (build bot image from this repo)

**Goal:** `docker compose` runs **bot + Lavalink** from a **locally built** image (`Dockerfile`), with bind mounts to **your repo’s** `local_audio/`, `lavalink/application.yml`, `logs/`.

### One-time / refresh staging

**`scripts/local_docker_build.sh prepare`** creates or refreshes **`.docker-local-build/`** (gitignored):

- Copies root **`docker-compose.yml`** and rewrites `./local_audio`, `./logs`, `./lavalink/...` to **absolute paths** under your clone.
- Writes **`docker-compose.local-build.yml`** (build `bot` from repo **`Dockerfile`**, image tag **`discord-bot-sandbox:local-docker-build`**, `hostname: bot`, music HTTP defaults).
- On **first** seed of **`.docker-local-build/.env`**, copies repo **`.env`** or **`.env.example`** and applies Compose-network tweaks (**`LAVALINK_URI`** → `http://lavalink:2333`, loopback **`DATABASE_URL`** → `@postgres:5432` when applicable).

**`prepare-build`** runs **`prepare`** then **`docker compose build bot`** (no `up`).

### Daily use

| Script | What it does |
|--------|----------------|
| **`scripts/docker_compose_up.sh`** | Default **`--doppler`**: `doppler run -- docker compose …` from **`.docker-local-build/`**. Default compose args: **`up --build -d`**. **`--env`**: compose only (staging **`.env`** must exist). Supports **`--dir`** / **`--workdir`** for an alternate staging folder. Pass-through: **`./scripts/docker_compose_up.sh logs -f bot`**. |
| **`scripts/local_docker_deploy.sh`** | **`compose down`** then **`docker_compose_up.sh`** with the same flags (full recycle). |

If **`.docker-local-build/`** is missing, **`docker_compose_up.sh`** runs **`local_docker_build.sh prepare`** first.

**Bundled Postgres / pgAdmin:** controlled by **`COMPOSE_PROFILES`** in the **staging** `.env` (see **[POSTGRES.md](POSTGRES.md)**). Root **`docker-compose.yml`** is canonical; staging is a copy with rewritten paths.

---

## Standalone bundle (ZIP + GHCR image)

**Goal:** One directory on a server **without** cloning the repo; compose pulls **`ghcr.io/jj3571/discord-bot:latest`** (or your fork’s image if you change compose).

| Artifact | Role |
|----------|------|
| **`discord-bot-standalone.zip`** | From GitHub Releases, or build locally: **`scripts/build_deploy_bundle.sh`** → **`dist/discord-bot-standalone.zip`**. |
| **`startup_script.sh`** | Same flags as **`run_bot.sh`**: default **`--doppler`** (Doppler writes **`.env`** then compose); **`--env`** uses existing **`.env`**; **`--dir`** for bundle root. Default compose: **`up --pull always -d`**. |
| **`docker_deploy.sh`** | **`compose down`** + **`startup_script.sh`** (pass-through flags). |

Layout and Postgres profiles are documented in **`scripts/deploy_bundle/README.md`** (in-repo copy of the bundled README).

---

## Maintainer / packaging scripts

| Script | Audience | Purpose |
|--------|----------|---------|
| **`scripts/build_deploy_bundle.sh`** | Maintainers | Regenerate **`dist/discord-bot-standalone/`** + **`.zip`** from canonical **`docker-compose.yml`**, **`.env.example`**, Lavalink example, bundle helpers. |
| **`scripts/tag_release.sh`** | Maintainers | Release tagging helper (see script header). |

---

## Postgres helper scripts

| Script | When to use |
|--------|------------|
| **`scripts/postgres_local/start.sh`** | Bare-metal bot + Postgres only in Docker (see **`scripts/postgres_local/README.md`**). |
| **`scripts/postgres_local/stop.sh`** / **`status.sh`** | Stop or check that local Postgres stack. |
| **`scripts/postgres_migrate_hosted_to_local.sh`** | Copy data **hosted → local** (or swap URLs for **local → hosted**) via **`postgres_dump_and_restore_helpers.py`**. |
| **`scripts/postgres_dump_and_restore_helpers.py`** | Low-level **`pg_dump`** / **`pg_restore`** (`DATABASE_URL` in env). |

---

## Docker Compose quick reference

Commands below assume the correct **project directory** and **compose files** for your workflow.

### Clone + local build (staging)

```bash
docker compose --project-directory /path/to/repo/.docker-local-build \
  -f docker-compose.yml -f docker-compose.local-build.yml ps
docker compose --project-directory /path/to/repo/.docker-local-build \
  -f docker-compose.yml -f docker-compose.local-build.yml logs -f bot
```

Or use **`./scripts/docker_compose_up.sh`** so Doppler and defaults stay consistent.

### Repo root (canonical file only)

Some contributors run plain compose from the repo root with the **published** image (no local build override). You must align **`DATABASE_URL`**, **`COMPOSE_PROFILES`**, and image tags with **`docker-compose.yml`**.

### Bundle directory

```bash
cd /path/to/discord-bot-standalone
docker compose ps
docker compose logs -f lavalink
```

**Profiles:** set **`COMPOSE_PROFILES`** in **`.env`** (e.g. **`bundled-db`**, **`bundled-db,admin-ui`**). See **[POSTGRES.md](POSTGRES.md)**.

---

## Moving between databases

### Legacy SQLite → PostgreSQL

Runtime today is **PostgreSQL only**. Legacy **`databases/*.db`** files (see **`server_configs/database_config.py`**) are not used by the running bot.

1. Provision Postgres (local, Neon, bundled compose, etc.) and set **`DATABASE_URL`**.
2. Run **`db/ddl.py`** initialization once by **starting the bot** against that URL (or run tooling that calls **`init_all_schemas`**).
3. One-time data copy from SQLite files:

```bash
uv run python scripts/migrate_sqlite_files_to_postgres_once.py --dry-run
uv run python scripts/migrate_sqlite_files_to_postgres_once.py
# Optional single schema:
# uv run python scripts/migrate_sqlite_files_to_postgres_once.py --only economy
```

Use a **staging** database first; never paste production URLs into public channels.

### Local PostgreSQL → Neon (hosted)

1. **Stop** every bot process using the local database (avoid dual writers).
2. **Dump** from local and **restore** to Neon (custom format helpers):

```bash
DATABASE_URL='postgresql://...@127.0.0.1:5432/discord_bot' \
  uv run python scripts/postgres_dump_and_restore_helpers.py dump --output /tmp/bot.dump
DATABASE_URL='postgresql://...@neon.../neondb?sslmode=require' \
  uv run python scripts/postgres_dump_and_restore_helpers.py restore --input /tmp/bot.dump --clean --if-exists
```

Or use **`postgres_migrate_hosted_to_local.sh`** with **`SOURCE_DATABASE_URL`** = local and **`TARGET_DATABASE_URL`** = Neon.

3. **Point secrets** at Neon: set **`DATABASE_URL`** in Doppler / **`.env`**.
4. **Docker:** remove **`bundled-db`** from **`COMPOSE_PROFILES`** so the compose Postgres service does not run (and ensure **`DATABASE_URL`** is **not** empty — see **[POSTGRES.md](POSTGRES.md)**).
5. **Verify:** `uv run python admin_tools/verify_databases.py`, then start the bot.

### Neon → local PostgreSQL (or bundled Postgres in compose)

1. Stop the bot against Neon.
2. Restore into local/bundled Postgres:

```bash
SOURCE_DATABASE_URL='postgresql://...@neon...?sslmode=require' \
TARGET_DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
  ./scripts/postgres_migrate_hosted_to_local.sh
```

Adjust **`TARGET_DATABASE_URL`** if you use **`postgres_local`**, a non-default port, or the bot container hostname **`postgres`** only from *inside* compose (for host-side restore, use **`127.0.0.1`** and the mapped port).

3. Set **`DATABASE_URL`** (and **`COMPOSE_PROFILES=bundled-db`** if you use bundled Postgres). Verify as above.

---

## See also

- **[README.md](../README.md)** — layout, Lavalink, VPS bundle overview  
- **[POSTGRES.md](POSTGRES.md)** — profiles, URLs, pgAdmin, risks  
- **[DEPLOY_DROPLET.md](DEPLOY_DROPLET.md)** — systemd-oriented VPS deploy  
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — clone, Docker staging, bundle build  
