# Agent instructions

This is L.I.L.I.T.H., a single-guild Discord bot. Humans and coding agents (local or Cursor Cloud) should follow this file together with [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). CONTRIBUTING is the source of truth for PR process, cog layout, and local Docker. This file is the short agent-oriented version plus Cloud-only setup.

## Repo facts

- Python 3.12–3.13 (local target: 3.13). Package manager: [uv](https://docs.astral.sh/uv/).
- App code lives under `src/main_bot/`. Production slash-command cogs: `src/main_bot/cogs/production/`. Experiments: `src/main_bot/cogs/development/`. `testing/`, `debugging/`, and `archived/` are not for new work.
- `main_bot/main.py` loads production cogs, then development cogs only when `LOAD_DEVELOPMENT_COGS` is true (or when that env is unset and `DEVELOPMENT_COG_EXTENSIONS_ENABLED` is true in `main.py`; the code default is currently false).
- Tests: `uv sync --group dev` then `uv run pytest`. Match [.github/workflows/ci.yml](.github/workflows/ci.yml): Postgres on `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/testdb` and `DISCORD_BOT_TOKEN=ci-placeholder-token`. Tests that need a real pool skip when `DATABASE_URL` is empty (see `tests/conftest.py`).
- Do not treat `scripts/bot.sh` as the contributor path. That script pulls the published GHCR image. Code changes must use `./scripts/docker_compose_up.sh` (see CONTRIBUTING Option B).
- Schema is stable. Do not change PostgreSQL DDL without an issue, a migration path, and maintainer agreement.

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

Secrets belong in Doppler (local) or Cursor Secrets (cloud). Never commit `.env`, Doppler tokens, Discord tokens, or guild IDs.

## Verify before you open a PR

1. `uv run pytest` (with CI-style `DATABASE_URL` and a placeholder `DISCORD_BOT_TOKEN` is enough for unit tests).
2. If you changed Python, cogs, or the Dockerfile, run the local image build: `./scripts/docker_compose_up.sh` (or `./scripts/local_docker_build.sh prepare-build` if you only need to prove the image builds).
3. Do not open a PR until pytest is green. For command behavior, wait until a human has tried the change on the **development** Discord guild (see Cloud section below).

---

## Cursor Cloud specific instructions

Cloud agents run on an isolated Ubuntu VM, not the maintainer laptop. They clone this repo, work on a `cursor/…` branch, and should treat the VM as a contributor checkout.

### Secrets (do not bake into the snapshot)

Cursor injects dashboard secrets at **agent start**, not into Builds. Set them once in [Cloud Agents → Secrets](https://cursor.com/dashboard/cloud-agents). New VMs pick them up automatically. Do not put secrets in `.cursor/environment.json` or this file.

**Preferred:** a Doppler **service token** scoped to a **development** config (not production). Store it as a Cursor **Runtime Secret** named `DOPPLER_TOKEN`. Then:

```bash
doppler secrets download --format env --no-file > .env
# or, for Compose:
./scripts/docker_compose_up.sh --doppler
```

See [docs/SECRETS_DOPPLER.md](docs/SECRETS_DOPPLER.md). Compose still interpolates `${VAR}` from `.env` when that file exists; downloading to `.env` (gitignored) is the reliable path. Never `git add` that file.

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
4. After code changes that need a live bot:

```bash
cp lavalink/application.yml.example lavalink/application.yml
mkdir -p logs local_audio/music
./scripts/docker_compose_up.sh          # --env after .env exists
# or:
./scripts/docker_compose_up.sh --doppler
./scripts/docker_compose_up.sh logs -f bot
```

Music/Lavalink is optional for most cog tasks. If voice is not in scope, still let Compose start; do not debug Lavalink unless the issue is about music.

Resource note: bot + Postgres + Lavalink is heavy on the default Cloud VM. If Compose fails for memory, fall back to pytest plus `./scripts/run_bot.sh` (host Python, still needs Postgres and the same `.env`).

### Test, then PR (do not reverse this)

Default Cloud Agent behavior is to push a branch and open a draft PR. For this repo:

1. Implement against the issue.
2. Run `uv run pytest`.
3. Bring the **development** bot online with `docker_compose_up.sh` so a human can click the slash command in the dev guild.
4. Wait for a follow-up that testing passed (or fix what they report). The VM must stay up during that loop; do not treat the run as finished until they say so.
5. Then open a **draft** PR that links `Fixes #N`. Do not merge. Do not request review on production-sensitive changes until a human has tested in Discord.

If the launch surface supports it (`autopr=false` in Slack, `autoCreatePR: false` on the API), keep PR creation off until step 5.

### What Cloud agents must not do

- Point the running bot at the production guild
- Commit `.env`, Doppler tokens, or Cursor secrets
- Run `scripts/tag_release.sh` or push version tags
- Change deploy workflows to ship untested images
- Treat GitHub issue spam as a reason to keep spending; only work issues you were asked to work
