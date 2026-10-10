# Agent instructions

This is L.I.L.I.T.H., a single-guild Discord bot. Humans and coding agents (local or Cursor Cloud) should follow this file together with [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). CONTRIBUTING is the source of truth for PR process, cog layout, and local Docker. This file is the short agent-oriented version plus Cloud-only setup.

## Repo facts

- Python 3.12–3.13 (local target: 3.13). Package manager: [uv](https://docs.astral.sh/uv/).
- App code lives under `src/main_bot/`. Production slash-command cogs: `src/main_bot/cogs/production/`. Experiments: `src/main_bot/cogs/development/`. `testing/`, `debugging/`, and `archived/` are not for new work.
- `main_bot/main.py` loads production cogs, then development cogs only when `LOAD_DEVELOPMENT_COGS` is true (or when that env is unset and `DEVELOPMENT_COG_EXTENSIONS_ENABLED` is true in `main.py`; the code default is currently false).
- Tests: `uv sync --group dev` then `uv run pytest`. Match [.github/workflows/ci.yml](.github/workflows/ci.yml): Postgres on `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/testdb` and `DISCORD_BOT_TOKEN=ci-placeholder-token`. Tests that need a real pool skip when `DATABASE_URL` is empty (see `tests/conftest.py`).
- Do not treat `scripts/bot.sh` as the contributor path. That script pulls the published GHCR image. Code changes must use `./scripts/docker_compose_up.sh` (see CONTRIBUTING Option B).
- Schema is stable. Do not change PostgreSQL DDL without an issue, a migration path, and maintainer agreement.
- Guild snowflakes (channels, roles, emojis, MTG lists, etc.) are stored in Postgres `guild_config` and edited with `.setup`. Do not re-add them to `.env.example` / Compose.

## Before changing code

1. There should already be a GitHub issue. Link it in the PR body as `Fixes #N`.
2. Branch names: `feature/issue-N-short-slug`, `fix/…`, `docs/…`.
3. Prefer [docs/CONVENTIONAL_COMMITS.md](docs/CONVENTIONAL_COMMITS.md) for commit messages.
4. Do not tag releases (`scripts/tag_release.sh`), push `v*.*.*` tags, or touch VPS/GHCR deploy. Maintainers do that.

## What to edit together

If you add or rename an environment variable, update all three:

1. `.env.example`
2. [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
3. The `environment:` block in `docker-compose.yml`

Guild channel/role/emoji knobs are **not** env vars — they live in Postgres and are edited with `.setup`. Secrets belong in Doppler (local) or Cursor Secrets (cloud), delivered via a host `.env` file. Never commit `.env`, Doppler tokens, Discord tokens, or guild IDs.

## Verify before you open a PR

1. `uv run pytest` (with CI-style `DATABASE_URL` and a placeholder `DISCORD_BOT_TOKEN` is enough for unit tests).
2. Do not open a PR until pytest is green. For Discord command behavior, wait until a human has tried the change on the **development** guild (see offer-to-bring-up below).

## After implementing: offer a local Docker bring-up

When the change affects bot runtime (cogs, `main.py`, Dockerfile, Compose, guild settings, slash/prefix commands), **do not** start Docker unprompted. After the code change and a green `uv run pytest`:

1. Ask the human whether they want a **local Docker image built and brought online** on the development guild so they can click through the change.
2. Only if they say yes, run the contributor stack (below). If they decline, stop at pytest and wait for further instructions (or open a draft PR only when they asked for one).
3. If they accept, keep the session available until they report Discord testing results (or ask you to fix something).

**Reliable bring-up** (local Agent or Cloud VM — same scripts):

```bash
# Secrets → gitignored .env (preferred over compose --doppler alone)
doppler secrets download --format env --no-file > .env
# Strip accidental surrounding quotes on values (Doppler/env downloads sometimes wrap tokens in "…")
# then:
cp lavalink/application.yml.example lavalink/application.yml   # once if missing
mkdir -p logs local_audio/music
./scripts/docker_compose_up.sh          # builds local image + starts bot/postgres/lavalink
./scripts/docker_compose_up.sh logs -f bot
```

Notes:

- Use development Doppler / tokens only. Never production.
- Leave `DATABASE_URL` empty and use `COMPOSE_PROFILES=bundled-db` for the local stack unless the human says otherwise.
- Compose must not interpolate `DISCORD_BOT_TOKEN` via `${DISCORD_BOT_TOKEN}` in `environment:` — the token is supplied through `env_file: .env` (see `docker-compose.yml`). Prefer download-to-`.env`, then `./scripts/docker_compose_up.sh` (default `--env`).
- Only one process may use a given bot token. If the development bot is already online elsewhere, say so and do not start a second instance.
- Image-build-only (no Discord): `./scripts/local_docker_build.sh prepare-build`.

---

## Cursor Cloud specific instructions

Cloud agents run on an isolated Ubuntu VM, not the maintainer laptop. They clone this repo, work on a `cursor/…` branch, and should treat the VM as a contributor checkout.

### Secrets (do not bake into the snapshot)

Cursor injects dashboard secrets at **agent start**, not into Builds. Set them once in [Cloud Agents → Secrets](https://cursor.com/dashboard/cloud-agents). New VMs pick them up automatically. Do not put secrets in `.cursor/environment.json` or this file.

**Preferred:** a Doppler **service token** scoped to a **development** config (not production). Store it as a Cursor **Runtime Secret** named `DOPPLER_TOKEN`. Then download into `.env` and use the default compose path (see **After implementing: offer a local Docker bring-up**). See [docs/SECRETS_DOPPLER.md](docs/SECRETS_DOPPLER.md). Never `git add` that file.

**Fallback:** copy only the development-guild keys into Cursor Secrets (`DISCORD_BOT_TOKEN`, `APPLICATION_ID`, `GUILD_ID`, plus the channel/role IDs that guild needs). Use type **Runtime Secret** for tokens so they redact from transcripts. Dump them to `.env` the same way CONTRIBUTING does (`cp .env.example .env`, then fill from the environment).

**Forbidden in the cloud environment**

- Production Discord bot token, production `GUILD_ID`, or production Doppler config
- VPS host credentials, GHCR deploy keys, Doppler tokens for prod

Pytest does **not** need real Discord. For tests, export the CI placeholders even if Doppler is configured:

```bash
export DATABASE_URL="${TEST_DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/testdb}"
export DISCORD_BOT_TOKEN=ci-placeholder-token
uv run pytest
```

Only one process may use a given bot token. Do not start the cloud bot while the same development token is already online on the laptop.

### Environment / Docker

The contributor stack is Docker Compose with a **locally built** bot image, bundled Postgres (`COMPOSE_PROFILES=bundled-db`, leave `DATABASE_URL` empty), and Lavalink.

Cloud VMs do not ship Docker by default. The saved Cloud environment should:

1. Install `uv`, Python 3.13, Docker CE, the Compose plugin, and (if using Doppler) the Doppler CLI.
2. `install`: `uv sync --group dev` (idempotent). Optionally start a disposable Postgres for pytest.
3. `start`: `sudo service docker start` if the image includes Docker. Nested Docker needs `fuse-overlayfs` / `iptables-legacy`; see [Cursor: Running Docker](https://cursor.com/docs/cloud-agent/setup#running-docker).
4. After code changes that need a live bot: follow **After implementing: offer a local Docker bring-up** (ask first; do not auto-start Compose).

Music/Lavalink is optional for most cog tasks. If voice is not in scope, still let Compose start when the human accepted bring-up; do not debug Lavalink unless the issue is about music.

Resource note: bot + Postgres + Lavalink is heavy on the default Cloud VM. If Compose fails for memory, fall back to pytest plus `./scripts/run_bot.sh` (host Python, still needs Postgres and the same `.env`).

### Test, then PR (do not reverse this)

Default Cloud Agent behavior is to push a branch and open a draft PR. For this repo:

1. Implement against the issue.
2. Run `uv run pytest`.
3. **Ask** whether to build/bring up the development bot (see offer-to-bring-up). Only then run `docker_compose_up.sh` so a human can exercise the change in the dev guild.
4. If they accepted bring-up, wait for a follow-up that testing passed (or fix what they report). The VM must stay up during that loop; do not treat the run as finished until they say so.
5. Then open a **draft** PR that links `Fixes #N`. Do not merge. Do not request review on production-sensitive changes until a human has tested in Discord (or explicitly waived Discord testing).

If the launch surface supports it (`autopr=false` in Slack, `autoCreatePR: false` on the API), keep PR creation off until step 5.

### What Cloud agents must not do

- Point the running bot at the production guild
- Commit `.env`, Doppler tokens, or Cursor secrets
- Run `scripts/tag_release.sh` or push version tags
- Change deploy workflows to ship untested images
- Treat GitHub issue spam as a reason to keep spending; only work issues you were asked to work
