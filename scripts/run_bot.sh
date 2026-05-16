#!/usr/bin/env bash
#
# Run the bot with uv: Doppler-injected secrets (--doppler) or the current
# environment (--env). Default working directory is the repo root (parent of
# this scripts/ directory). Override with --dir for a nonstandard directory layout.
#
# Examples:
#   ./scripts/run_bot.sh --doppler
#   ./scripts/run_bot.sh --env
#   ./scripts/run_bot.sh --doppler --dir /path/to/repo
#   ./scripts/run_bot.sh --env -- --some-main-bot-flag
#

set -euo pipefail
export PYTHONUNBUFFERED=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  cat >&2 <<'EOF'
Usage: run_bot.sh (--doppler|--env) [--dir DIR|-C DIR] [--] [args to python -m main_bot]

  --doppler    Run under: doppler run -- uv run python -m main_bot
  --env        Run: uv only (export / load DATABASE_URL, DISCORD_BOT_TOKEN, etc. yourself — uv does not read .env)
  --dir, -C    Working directory (default: repo root = parent of scripts/)

EOF
}

MODE=""
ROOT=""
PASS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --doppler)
      if [[ -n "$MODE" && "$MODE" != doppler ]]; then
        echo "run_bot.sh: use only one of --doppler or --env" >&2
        exit 1
      fi
      MODE=doppler
      shift
      ;;
    --env)
      if [[ -n "$MODE" && "$MODE" != env ]]; then
        echo "run_bot.sh: use only one of --doppler or --env" >&2
        exit 1
      fi
      MODE=env
      shift
      ;;
    --dir|-C)
      if [[ $# -lt 2 ]]; then
        echo "run_bot.sh: $1 requires a directory" >&2
        exit 1
      fi
      ROOT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      PASS+=("$@")
      break
      ;;
    *)
      PASS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$MODE" ]]; then
  usage
  exit 1
fi

ROOT="${ROOT:-$DEFAULT_ROOT}"
if [[ ! -d "$ROOT" ]]; then
  echo "run_bot.sh: not a directory: $ROOT" >&2
  exit 1
fi

cd "$ROOT"

if [[ "$MODE" == doppler ]]; then
  exec doppler run -- uv run python -m main_bot "${PASS[@]}"
else
  exec uv run python -m main_bot "${PASS[@]}"
fi
