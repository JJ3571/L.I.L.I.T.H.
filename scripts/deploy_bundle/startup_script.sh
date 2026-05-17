#!/usr/bin/env bash
#
# Docker Compose entrypoint for the standalone bundle (ZIP next to docker-compose.yml).
# Flag semantics align with repo scripts/run_bot.sh:
#   --doppler (default) — doppler secrets download → .env, then docker compose …
#   --env               — use existing .env only (no Doppler download); manual/Doppler-run workflows
#   --dir DIR, -C DIR   — bundle root (default: directory containing this script)
#
# Expect docker-compose.yml, .env.template, and this script in ONE folder with docker compose.
#
# Alternate (no .env on disk): doppler run -- docker compose up --pull always -d
#
# Usage:
#   ./startup_script.sh                      → doppler → .env; compose up --pull always -d
#   ./startup_script.sh --env                → compose only (requires .env)
#   ./startup_script.sh up --pull always     → doppler → .env; compose up … (omit -d to stream logs)

set -euo pipefail
export PYTHONUNBUFFERED=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_BUNDLE_DIR="$SCRIPT_DIR"

usage() {
  cat >&2 <<'EOF'
Usage: startup_script.sh [--doppler|--env] [--dir DIR|-C DIR] [--] [docker compose args]

  --doppler    Download secrets from Doppler CLI into .env, then run docker compose (default).
  --env        Skip Doppler download; run docker compose using existing .env in this folder.
  --dir, -C    Bundle directory (default: directory containing this script).

If no compose args are given, defaults to: up --pull always -d

EOF
}

MODE=""
DIR_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --doppler)
      if [[ -n "$MODE" && "$MODE" != doppler ]]; then
        echo "startup_script.sh: use only one of --doppler or --env" >&2
        exit 1
      fi
      MODE=doppler
      shift
      ;;
    --env)
      if [[ -n "$MODE" && "$MODE" != env ]]; then
        echo "startup_script.sh: use only one of --doppler or --env" >&2
        exit 1
      fi
      MODE=env
      shift
      ;;
    --dir|-C)
      if [[ $# -lt 2 ]]; then
        echo "startup_script.sh: $1 requires a directory" >&2
        exit 1
      fi
      DIR_OVERRIDE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

MODE="${MODE:-doppler}"
export BUNDLE_DIR="${DIR_OVERRIDE:-$DEFAULT_BUNDLE_DIR}"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "startup_script.sh: not a directory: $BUNDLE_DIR" >&2
  exit 1
fi

cd "$BUNDLE_DIR"

COMPOSE_ARGS=("$@")

if [[ "$MODE" == doppler ]]; then
  tmp="$(mktemp "${TMPDIR:-/tmp}/discord-bot-docker-.env.XXXXXX")"
  cleanup() { rm -f "$tmp"; }
  trap cleanup EXIT

  doppler secrets download --format env "$tmp"
  mv "$tmp" .env
  trap - EXIT
  chmod 600 .env || true
elif [[ ! -f .env ]]; then
  echo "startup_script.sh: --env requires .env in $BUNDLE_DIR (e.g. cp .env.template .env)" >&2
  exit 1
fi

if [[ ${#COMPOSE_ARGS[@]} -eq 0 ]]; then
  COMPOSE_ARGS=(up --pull always -d)
fi

exec docker compose "${COMPOSE_ARGS[@]}"
