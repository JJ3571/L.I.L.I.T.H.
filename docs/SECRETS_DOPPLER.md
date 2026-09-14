# Optional Doppler secrets

This project uses a root level`.env` file as the default. I prefer using Doppler for secrets management, but this is entirely optional.

(See [QUICKSTART.md](QUICKSTART.md) for setup, and [CONFIGURATION.md](CONFIGURATION.md) for all variable names.)

## Scripts with a `--doppler` flag

These scripts accept `--doppler` and inject secrets with the Doppler CLI:

```bash
./scripts/run_bot.sh --doppler
./scripts/docker_compose_up.sh --doppler
```

## `bot.sh` has no `--doppler` flag

`scripts/bot.sh` always reads the project `.env` file (and Compose substitution).

Instead, use one of these approaches.

### Recommended — download secrets into `.env`

1. Install the Doppler CLI.
2. Run `doppler setup` in the project directory.
3. Download secrets as env lines. (Assuming you already have secrets from [CONFIGURATION.md](CONFIGURATION.md) stored in Doppler.)

```bash
doppler secrets download --format env --no-file > .env
```

1. Start with `bot.sh` as usual.

```bash
./scripts/bot.sh up
```



### Alternate — wrap the command

You can also inject Doppler into the process environment in a single line:

```bash
doppler run -- ./scripts/bot.sh up
```

Compose still prefers values from `.env` for `${VAR}` substitution when that file is present.

## CI deploy

The GitHub Actions deploy workflow runs `docker compose up` against the `.env` file on the host. It does not call Doppler. Keep secrets in that `.env` file on the VPS.