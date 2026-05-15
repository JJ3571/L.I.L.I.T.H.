#!/usr/bin/env bash
# Local/dev: run bot WITHOUT Doppler. Load DATABASE_URL / DISCORD_BOT_TOKEN / etc yourself
# (export commands, IDE env, or source a compatible .env in your shell first).
#
# This script does not load `.env` for you — Compose does at container start; uv does not.

set -euo pipefail
export PYTHONUNBUFFERED=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec uv run python -m main_bot "$@"
