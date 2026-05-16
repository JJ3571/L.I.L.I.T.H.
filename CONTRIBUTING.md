# Contributing

This is a maintainer-run side project — no review SLA or roadmap promises. Contributions that **improve the bot for broad use** are welcome. Very guild-specific cogs may land here for now; if the tree gets crowded, we may reorganize folders or even separate out a plugin/module structure to keep cogs organized for general use.

---

## Before you open a pull request

1. **Open a GitHub issue first** (bug, feature, or discussion) and describe the change.
2. **Link that issue in your PR** body (`Fixes #123` or “See #123”). Blind drive-by PRs without context are harder to review and will be ignored. 
3. Follow **branch naming** examples: `feature/issue-42-mtg-throttle`, `fix/logging-embed-width`, `docs/setup-doppler`, `chore/ci-uv-cache`. Pick a prefix (`feature/`, `fix/`, `docs/`, `chore/`, …) and include a short slug/explanation (issue number optional but helpful).

---

## Reviews & merging

- Currently **one maintainer**, just me — effectively **one approval** to merge.
- **I would prefer GitHub’s squash merge** when merging PRs (one commit per change on `main`), but **a normal merge commit is still fine**. You don’t need a special local workflow—no obligation to rebase for a perfectly straight line unless you’re asked when resolving conflicts.

---

## Python & tooling

- **Target Python 3.13** for development and local testing (CI uses a version compatible with `requires-python` in `pyproject.toml`). Bumping the supported range is only when something like Nextcord requires it. Project was originally dependent on Python 3.12 but was bumped up with Nextcord v3. 
- This project uses **[uv](https://docs.astral.sh/uv/)**. Run — `uv sync` (include `--group dev` for tests), then run the bot via the scripts below.

### Running the bot locally (no Docker)

- **Doppler:** `./scripts/run_bot_doppler.sh`
- **Plain env** (you export / load vars yourself — `uv` does not read `.env`): `./scripts/run_bot_env.sh`

`scripts/run_bot.sh` is tailored to a **maintainer VPS layout** (`/home/discord_bot`); for a normal clone, use the two scripts above.

### Docker

- **Compose** (root [`docker-compose.yml`](docker-compose.yml)) and **`uv run`** paths should both remain working. See [`README.md`](README.md) (Setup & secrets) for Doppler vs `.env`.
- **Local Compose + image built from this repo:** [`scripts/docker_compose_local_image_test.sh`](scripts/docker_compose_local_image_test.sh) is the supported way to match production **without swapping the canonical Compose file** away from **`ghcr.io/...`**.
  - **`prepare`** (or invoking the script with no Docker args — it reruns **`prepare`** first) writes a staging tree (**`.docker-local-compose-test/`** by default, gitignored). That tree contains a copy of **`docker-compose.yml`** from repo root plus **`docker-compose.local-build.yml`**, which overrides the bot image to **`discord-bot-sandbox:local-compose-test`** built from the repo **`Dockerfile`**, sets **`hostname: bot`**, adjusts **`MUSIC_LOCAL_HTTP_*`** for the Compose network, stubs **`local_audio/`** and **`logs/`**, hydrates **`lavalink/application.yml`**, and on first run seeds **`.env`** from your repo **`.env`** or **`.env.example`**. Compose defaults the bot to **`http://lavalink:2333`** ( **`LAVALINK_DOCKER_URI`** — see **`docker-compose.yml`**); the script strips useless localhost **`LAVALINK_DOCKER_URI`** and can rewrite **`LAVALINK_URI`** in staging `.env` when still host-localhost. Later runs preserve your staging **`.env`**.
  - **Examples:** `./scripts/docker_compose_local_image_test.sh prepare` (no Docker); **`prepare-build`** (staging + **`docker compose build bot`**, no **`up`**); `./scripts/docker_compose_local_image_test.sh` (default **`docker compose up --build`**, starts Lavalink then bot via **`depends_on`** without blocking on Lavalink’s healthcheck); **`doppler run -- ./scripts/docker_compose_local_image_test.sh logs -f bot`**. Compose commands fail fast if Docker is unavailable (**`prepare`** / **`prepare-build`** still usable where noted).
  - **`--workdir DIR`** / **`DOCKER_LOCAL_IMAGE_TEST_WORKDIR`** move the staging directory if you prefer not to use **`.docker-local-compose-test/`**.
- **Standalone release ZIP (`discord-bot-standalone.zip`):** [`scripts/build_deploy_bundle.sh`](scripts/build_deploy_bundle.sh) assembles **`dist/discord-bot-standalone/`** and a **`dist/discord-bot-standalone.zip`** from the single-source files in the repo: slices **`docker-compose.yml`** from **`services:`** onward merged with **`scripts/deploy_bundle/docker-compose.bundle-header.frag`**, copies **`.env.example`** → **`bundle/.env.template`**, **`lavalink/application.yml.example`**, plus **`scripts/deploy_bundle/{README.md,startup_script.sh,rollout.sh}`**. **`dist/`** is gitignored; run locally to verify packaging or before publishing a Release.
- When you change **[`docker-compose.yml`](docker-compose.yml)**, **[`.env.example`](.env.example)**, or **`docs/DOPPLER_ENV_KEYS.md`** for the same Compose/env surface (for example **`BOT_LOG_FILE`**, **`logs/`** bind mount), also run **`./scripts/build_deploy_bundle.sh`** before release and note that in the PR so the unpacked ZIP stays in sync.

---

## Database

- **Any PostgreSQL** works for local dev; point `DATABASE_URL` at it. 
- **Existing schema (especially economy)** is treated as stable. Changes that break live instances need **strong justification**, a **migration / upgrade path**, and would align with a **major** semantic version bump — discuss in the issue first. 

---

## Cogs layout

- **`main_bot/cogs/production/`** — what ships for “real” deployments. **PRs should land finished, working cogs here** (or clearly extension points there).
- **`main_bot/cogs/development/`** — sandboxes for experiments; fine on `main` while WIP. Don’t rely on it for production stability. 
- Prefer **avoiding tight coupling** between cogs unless necessary; **economy / voice / shared “core”** patterns are reasonable import targets.
- **`testing/`**, **`debugging/`**, **`archived/`** — are moreso 'labeled' folder for holding older or non-working cogs; don’t move large refactors without coordination in the issue.

---

## Config & secrets

- New or renamed **environment variables**: update **`.env.example`**, **[`docs/DOPPLER_ENV_KEYS.md`](docs/DOPPLER_ENV_KEYS.md)**, and the **`environment:`** block in root **`docker-compose.yml`** (standalone ZIP is generated from those). Lavalink and local audio expectations stay in **`README.md`** and **`lavalink/application.yml.example`**.

---

## What to verify before asking for merge

1. **`uv run pytest`** (or match **`.github/workflows/ci.yml`**: `uv sync --group dev`, then `uv run pytest`).
2. **Manual check** of the behaviour you changed (you don’t need to click every slash command in the guild, but **your** feature/fix/path should be tested). For user-facing slash/embed changes, a **short note in the PR** (what you tested, Discord-side) helps.

---

## Versioning (expectation)

- Breaking changes to **public behaviour** or **data** (especially DB) should be called out in the issue/PR and routed through **[semantic versioning](https://semver.org/)** discussions when we cut releases.

---

## License & conduct

- No extra **license or CLA** requirements beyond what the repository already states (if empty, then that's still true).
- No separate **Code of Conduct** doc — still be respectful and constructive in issues and PRs. Be a normal human being, please. 
