#!/usr/bin/env bash
# Start local Postgres (Docker) for bare-metal bot runs — matches default credentials in `.env.example`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! docker info >/dev/null 2>&1; then
	echo "postgres_local/start.sh: Docker does not appear to be running." >&2
	exit 1
fi

if [[ -f "$ROOT/.env" ]]; then
	set -a
	# shellcheck source=/dev/null
	source "$ROOT/.env"
	set +a
fi

docker compose -f "$SCRIPT_DIR/docker-compose.yml" --project-directory "$SCRIPT_DIR" up -d

port="${POSTGRES_HOST_PORT:-5432}"
echo "Postgres listening on 127.0.0.1:${port} (defaults: user/password/db bot/bot/discord_bot)."
echo "Example: export DATABASE_URL=postgresql://bot:bot@127.0.0.1:${port}/discord_bot && ./scripts/run_bot.sh --env"
