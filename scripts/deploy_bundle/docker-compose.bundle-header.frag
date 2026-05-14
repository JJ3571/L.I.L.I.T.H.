# Discord bot + Lavalink (standalone package produced from this repo — no clone required).
#
# Secrets via `.env`: copy `.env.template` → `.env`, or run `./startup_script.sh` (Doppler → `.env`).
# Compose substitutes `${VAR}` from `.env` or your shell. See README.md in this folder.
#
# `./local_audio` and `./lavalink/application.yml` are resolved next to this file.
#
# Passing only `DOPPLER_TOKEN=…` to compose does NOT inject DATABASE_URL etc. Prefer
# `./startup_script.sh` or `doppler run -- docker compose up …`:
# https://docs.doppler.com/docs/docker-compose#option-2-container-env-vars
#
