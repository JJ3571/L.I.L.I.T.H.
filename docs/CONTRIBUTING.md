# Contributing

This is a maintainer-run side project. There is no review SLA. Contributions that improve the bot for broad use are welcome.

Clone this repository when you need the source tree. Typical reasons:

- Open a pull request
- Add or edit custom cogs
- Change bot code and test a local Docker image

Basic clone-and-build steps are in [QUICKSTART.md — Option B](QUICKSTART.md#option-b--clone-and-build-a-local-image). This document covers contribution rules and deeper local workflows.

To run the published image without a clone, see [QUICKSTART.md — Option A](QUICKSTART.md#option-a--install-script-published-image).

Cursor Cloud Agents (and other coding agents) should also read [AGENTS.md](../AGENTS.md).

## Before you open a pull request

1. Open a GitHub issue first. Describe the change.
2. Link that issue in the pull request body. E.g.: `Fixes #123`.
3. Use a clear branch name. Examples: `feature/issue-42-mtg-throttle`, `fix/logging-embed-width`, `docs/quickstart`.
4. Not required, but try and follow [CONVENTIONAL_COMMITS.md](CONVENTIONAL_COMMITS.md) for commit messages.



## Python and tooling

- Target Python 3.13 for local development. The project supports Python 3.12 and 3.13 per `pyproject.toml`.
- Use [uv](https://docs.astral.sh/uv/).
- Sync dependencies with `uv sync`. Add `--group dev` for tests.



## Run from a clone

After you clone, configure secrets the same way as the quick start.

```bash
cp .env.example .env
cp lavalink/application.yml.example lavalink/application.yml
mkdir -p logs local_audio/music
```

Set `DISCORD_BOT_TOKEN`, `APPLICATION_ID`, and `GUILD_ID` in `.env`. Leave `DATABASE_URL` empty for the bundled Postgres profile.

### Build a local Docker image  (for code changes)

Use this path when you change Python source, cogs, or the Dockerfile. Compose builds from this repository instead of pulling the Docker image from Github.

```bash
./scripts/docker_compose_up.sh
```

That command prepares `.docker-local-build/` if needed, builds the bot image, and starts the stack. Default secrets mode is `--env`.


| Task                   | Command                                         |
| ---------------------- | ----------------------------------------------- |
| Start or rebuild       | `./scripts/docker_compose_up.sh`                |
| Follow logs            | `./scripts/docker_compose_up.sh logs -f bot`    |
| Full recycle           | `./scripts/local_docker_deploy.sh`              |
| Prepare staging only   | `./scripts/local_docker_build.sh prepare`       |
| Prepare and build only | `./scripts/local_docker_build.sh prepare-build` |


See [SCRIPTS.md](SCRIPTS.md) for details.

### Host Python without Docker

```bash
uv sync --group dev
./scripts/run_bot.sh
```

See [BARE_METAL.md](BARE_METAL.md).

### Published image from a clone

You can run root `docker compose up -d` from a clone. That still pulls `ghcr.io/jj3571/discord-bot:latest`. Prefer the install script in [QUICKSTART.md](QUICKSTART.md) unless you already have the repository open for other work.

`scripts/bot.sh` wraps that same published-image compose file. Use it for backup, restore, and doctor checks. It does not build a local image.

## Database

Point `DATABASE_URL` at any PostgreSQL server, or use the bundled Compose profile. See [DATABASE.md](DATABASE.md).

Treat the existing schema as stable. Schema changes that break live instances need strong justification, a migration path, and a major version discussion in the issue first. 

## Cogs layout


| Path                                  | Role                                             |
| ------------------------------------- | ------------------------------------------------ |
| `main_bot/cogs/production/`           | Finished cogs for real deployments               |
| `main_bot/cogs/development/`          | Experiments. Do not rely on these for production |
| `testing/`, `debugging/`, `archived/` | Older or non-working cogs                        |


Prefer loose coupling between cogs. Shared economy and voice helpers are reasonable import targets.

To add a custom cog for local use:

1. Place the module under `src/main_bot/cogs/development/` or `production/`.
2. Confirm `main_bot/main.py` loads that package path.
3. Rebuild and run with `./scripts/docker_compose_up.sh`.

Admin command toggle docs:

- [coghelp/ADMIN_COMMAND_TOGGLE.md](coghelp/ADMIN_COMMAND_TOGGLE.md) — operator overview
- [coghelp/ADMIN_COMMAND_TOGGLE_GUIDE.md](coghelp/ADMIN_COMMAND_TOGGLE_GUIDE.md) — developer guide
- [coghelp/example_admin_cog.py](coghelp/example_admin_cog.py) — example snippet



## Config and secrets

When you add or rename an environment variable, update all of these files:

1. `[.env.example](../.env.example)`
2. [CONFIGURATION.md](CONFIGURATION.md)
3. The `environment:` block in `[docker-compose.yml](../docker-compose.yml)`

Lavalink and local audio details live in [MUSIC.md](MUSIC.md) and `lavalink/application.yml.example`.

Optional Doppler notes live in [SECRETS_DOPPLER.md](SECRETS_DOPPLER.md).

## What to verify before merge

1. Run `uv run pytest` (or match `.github/workflows/ci.yml`).
2. Manually test the behaviour you changed.
3. If you change container paths, run `./scripts/local_docker_build.sh prepare-build` or `./scripts/docker_compose_up.sh`.



## Versioning and releases

Call out breaking changes to public behaviour or data in the issue and pull request. Discuss semantic versioning before a release.

Maintainers cut versions with `./scripts/tag_release.sh` from the repository root.

1. The script detects the latest plain `vX.Y.Z` tag.
2. You choose patch, minor, major, or a custom version.
3. Optional: sync `pyproject.toml`, commit, create an annotated tag, and push.

Pushing `v*.*.*` triggers `.github/workflows/release.yml` (GHCR image and GitHub Release). `.github/workflows/deploy.yml` then deploys with Docker Compose. See [VPS_DEPLOY.md](VPS_DEPLOY.md).

Prefer a clean working tree before you tag.

## License and conduct
No extra license or CLA requirements beyond the repository statements. Be respectful in issues and pull requests!
