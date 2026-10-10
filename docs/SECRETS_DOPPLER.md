# Optional Doppler secrets

This project uses a root-level `.env` file as the **runtime default**. Doppler is optional: use it as the editor / source of truth for secrets, then download into `.env`.

(See [QUICKSTART.md](QUICKSTART.md) for setup, and [CONFIGURATION.md](CONFIGURATION.md) for variable names.)

## Recommended — download secrets into `.env`

1. Install the Doppler CLI.
2. Run `doppler setup` in the project directory (or set `DOPPLER_TOKEN` / project config on the VPS).
3. Download secrets as env lines:

```bash
doppler secrets download --format env --no-file > .env
```

4. Start with Compose / `bot.sh` as usual (they read `.env`).

```bash
./scripts/bot.sh up
```

Never commit `.env`.

## Scripts with a `--doppler` flag (optional shortcut)

These scripts can still inject secrets for a single process without writing `.env`:

```bash
./scripts/run_bot.sh --doppler
./scripts/docker_compose_up.sh --doppler
```

Prefer download-to-`.env` so Compose `${VAR}` substitution and the bot see the same file. `doppler run` does not populate Compose substitution from a missing `.env`.

## `bot.sh` has no `--doppler` flag

`scripts/bot.sh` always reads the project `.env` file (and Compose substitution). Use the download step above.

## CI / VPS deploy

The GitHub Actions [deploy workflow](../.github/workflows/deploy.yml) SSHs to the VPS and:

1. Runs `doppler secrets download --format env --no-file > .env` when the Doppler CLI is available on the host.
2. Runs `docker compose down` then `docker compose up -d --pull always` (no `doppler run`).

If Doppler is not installed on the VPS, keep a maintained `.env` in `DEPLOY_COMPOSE_DIR`. See [VPS_DEPLOY.md](VPS_DEPLOY.md).
