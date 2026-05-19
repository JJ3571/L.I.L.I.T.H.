#!/usr/bin/env bash
# Show container status and pg_isready against local Postgres.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
	set -a
	# shellcheck source=/dev/null
	source "$ROOT/.env"
	set +a
fi

docker compose -f "$SCRIPT_DIR/docker-compose.yml" --project-directory "$SCRIPT_DIR" ps

user="${POSTGRES_USER:-bot}"
db="${POSTGRES_DB:-discord_bot}"
if docker compose -f "$SCRIPT_DIR/docker-compose.yml" --project-directory "$SCRIPT_DIR" exec -T postgres \
	pg_isready -U "$user" -d "$db" 2>/dev/null; then
	echo "pg_isready: OK"
else
	echo "pg_isready: failed (is Postgres running? ./scripts/postgres_local/start.sh)" >&2
	exit 1
fi
