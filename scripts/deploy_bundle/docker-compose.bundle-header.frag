# Discord bot + Lavalink (standalone package produced from this repo — no clone required).
#
# Optional Postgres + pgAdmin use Compose profiles (see `.env` / `.env.template` `COMPOSE_PROFILES`):
#   bundled-db   → postgres:17-alpine (Neon-compatible); leave DATABASE_URL empty for the compose default.
#   admin-ui     → pgAdmin on loopback :5050 (use with bundled-db). See README.md + docs/POSTGRES.md in the repo.
#
# Secrets via `.env`: copy `.env.template` → `.env`, then `./startup_script.sh --env`,
# or `./startup_script.sh` / `--doppler` (default; Doppler CLI → `.env`). Same `--env` /
# `--doppler` / `--dir` flags as repo `scripts/run_bot.sh` (here: docker compose).
# Compose substitutes `${VAR}` from `.env` or your shell. See README.md in this folder.
#
# `./local_audio` and `./lavalink/application.yml` are resolved next to this file.
#
# Passing only `DOPPLER_TOKEN=…` to compose does NOT inject DATABASE_URL etc. Prefer
# `./startup_script.sh` or `doppler run -- docker compose up …`:
# https://docs.doppler.com/docs/docker-compose#option-2-container-env-vars
#
