#!/usr/bin/env bash
#
# Operator entry point for the root Docker Compose stack.
#
# Run from the directory that holds docker-compose.yml and .env, or pass --dir.
#
# Usage:
#   ./scripts/bot.sh up
#   ./scripts/bot.sh down
#   ./scripts/bot.sh restart
#   ./scripts/bot.sh update
#   ./scripts/bot.sh logs [service]
#   ./scripts/bot.sh status
#   ./scripts/bot.sh backup [output.dump]
#   ./scripts/bot.sh restore <input.dump>
#   ./scripts/bot.sh psql
#   ./scripts/bot.sh doctor
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# When installed via install.sh, scripts/ sits next to docker-compose.yml.
# When run from a git clone, scripts/ sits under the repo root.
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
	cat >&2 <<'EOF'
Usage: bot.sh [--dir DIR] <command> [args]

Commands:
  up                 Start the stack (docker compose up -d)
  down               Stop the stack (docker compose down)
  restart            Restart all services
  update             Pull images and recreate containers
  logs [service]     Follow logs (default: bot)
  status             Show compose ps and health
  backup [file]      Dump Postgres to a file (default: backups/bot-TIMESTAMP.dump)
  restore <file>     Restore Postgres from a custom-format dump
  psql               Open a psql shell against the bundled database
  doctor             Check Docker, .env, compose file, and required keys

Options:
  --dir, -C DIR      Compose project directory (default: parent of scripts/)
  -h, --help         Show this help

EOF
}

ROOT=""
CMD=""
PASS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
		--dir|-C)
			if [[ $# -lt 2 ]]; then
				echo "bot.sh: $1 requires a directory" >&2
				exit 1
			fi
			ROOT="$2"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			if [[ -z "$CMD" ]]; then
				CMD="$1"
				shift
			else
				PASS+=("$1")
				shift
			fi
			;;
	esac
done

ROOT="${ROOT:-$DEFAULT_ROOT}"
if [[ ! -d "$ROOT" ]]; then
	echo "bot.sh: not a directory: $ROOT" >&2
	exit 1
fi
cd "$ROOT"

if [[ -z "$CMD" ]]; then
	usage
	exit 1
fi

compose() {
	docker compose "$@"
}

require_compose_file() {
	if [[ ! -f docker-compose.yml && ! -f compose.yaml ]]; then
		echo "bot.sh: no docker-compose.yml in $ROOT" >&2
		exit 1
	fi
}

load_dotenv() {
	if [[ ! -f .env ]]; then
		return 0
	fi
	while IFS= read -r line || [[ -n "$line" ]]; do
		# Skip blank lines and comments.
		[[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
		if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
			export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
		fi
	done < .env
}

# Host-reachable DATABASE_URL for backup/restore/psql when using bundled Postgres.
host_database_url() {
	load_dotenv
	local url="${DATABASE_URL:-}"
	local user="${POSTGRES_USER:-bot}"
	local pass="${POSTGRES_PASSWORD:-bot}"
	local db="${POSTGRES_DB:-discord_bot}"
	local port="${POSTGRES_HOST_PORT:-5432}"

	if [[ -z "$url" || "$url" == *"@postgres:"* ]]; then
		echo "postgresql://${user}:${pass}@127.0.0.1:${port}/${db}?sslmode=disable"
	else
		echo "$url"
	fi
}

cmd_up() {
	require_compose_file
	compose up -d
}

cmd_down() {
	require_compose_file
	compose down
}

cmd_restart() {
	require_compose_file
	compose restart
}

cmd_update() {
	require_compose_file
	compose pull
	compose up -d --pull always
}

cmd_logs() {
	require_compose_file
	local svc="${PASS[0]:-bot}"
	compose logs -f "$svc"
}

cmd_status() {
	require_compose_file
	compose ps
	echo
	if compose ps --status running --services 2>/dev/null | grep -qx postgres; then
		compose exec -T postgres pg_isready -U "${POSTGRES_USER:-bot}" -d "${POSTGRES_DB:-discord_bot}" || true
	fi
}

cmd_backup() {
	require_compose_file
	load_dotenv
	mkdir -p backups
	local out="${PASS[0]:-}"
	if [[ -z "$out" ]]; then
		out="backups/bot-$(date +%Y%m%d-%H%M%S).dump"
	fi
	local url
	url="$(host_database_url)"
	echo "Dumping database to ${out}"
	if command -v pg_dump >/dev/null 2>&1; then
		DATABASE_URL="$url" pg_dump -Fc --no-owner --no-acl -f "$out" "$url"
	else
		# Fall back to pg_dump inside the postgres container.
		compose exec -T postgres pg_dump -U "${POSTGRES_USER:-bot}" -d "${POSTGRES_DB:-discord_bot}" -Fc --no-owner --no-acl >"$out"
	fi
	echo "Backup written: ${out}"
}

cmd_restore() {
	require_compose_file
	if [[ ${#PASS[@]} -lt 1 ]]; then
		echo "bot.sh restore: provide an input dump file" >&2
		exit 1
	fi
	local input="${PASS[0]}"
	if [[ ! -f "$input" ]]; then
		echo "bot.sh restore: file not found: $input" >&2
		exit 1
	fi
	load_dotenv
	echo "CAUTION: This replaces data in the target database."
	local url
	url="$(host_database_url)"
	if command -v pg_restore >/dev/null 2>&1; then
		pg_restore --no-owner --no-acl --clean --if-exists -d "$url" "$input"
	else
		compose exec -T postgres pg_restore -U "${POSTGRES_USER:-bot}" -d "${POSTGRES_DB:-discord_bot}" --no-owner --no-acl --clean --if-exists <"$input"
	fi
	echo "Restore complete: ${input}"
}

cmd_psql() {
	require_compose_file
	load_dotenv
	compose exec postgres psql -U "${POSTGRES_USER:-bot}" -d "${POSTGRES_DB:-discord_bot}"
}

cmd_doctor() {
	local ok=0
	echo "Checking Docker…"
	if ! command -v docker >/dev/null 2>&1; then
		echo "FAIL: docker not found"
		ok=1
	elif ! docker info >/dev/null 2>&1; then
		echo "FAIL: docker daemon not reachable"
		ok=1
	else
		echo "OK: docker"
	fi

	echo "Checking Compose file…"
	if [[ -f docker-compose.yml || -f compose.yaml ]]; then
		echo "OK: compose file present"
	else
		echo "FAIL: no docker-compose.yml in $ROOT"
		ok=1
	fi

	echo "Checking .env…"
	if [[ ! -f .env ]]; then
		echo "FAIL: .env missing (copy from .env.example)"
		ok=1
	else
		echo "OK: .env present"
		load_dotenv
		for key in DISCORD_BOT_TOKEN APPLICATION_ID GUILD_ID; do
			val="${!key:-}"
			if [[ -z "$val" ]]; then
				echo "FAIL: $key is empty in .env"
				ok=1
			else
				echo "OK: $key is set"
			fi
		done
		if [[ -z "${DATABASE_URL:-}" ]]; then
			profiles="${COMPOSE_PROFILES:-}"
			if [[ "$profiles" == *"bundled-db"* ]]; then
				echo "OK: DATABASE_URL empty with bundled-db profile (expected)"
			else
				echo "FAIL: DATABASE_URL empty and COMPOSE_PROFILES lacks bundled-db"
				ok=1
			fi
		else
			echo "OK: DATABASE_URL is set"
		fi
	fi

	echo "Checking lavalink/application.yml…"
	if [[ -f lavalink/application.yml ]]; then
		echo "OK: lavalink/application.yml present"
	else
		echo "WARN: lavalink/application.yml missing (copy from application.yml.example)"
	fi

	if [[ $ok -eq 0 ]]; then
		echo
		echo "Doctor: all required checks passed."
	else
		echo
		echo "Doctor: one or more checks failed."
	fi
	return "$ok"
}

case "$CMD" in
	up) cmd_up ;;
	down) cmd_down ;;
	restart) cmd_restart ;;
	update) cmd_update ;;
	logs) cmd_logs ;;
	status) cmd_status ;;
	backup) cmd_backup ;;
	restore) cmd_restore ;;
	psql) cmd_psql ;;
	doctor)
		cmd_doctor
		exit $?
		;;
	*)
		echo "bot.sh: unknown command: $CMD" >&2
		usage
		exit 1
		;;
esac
