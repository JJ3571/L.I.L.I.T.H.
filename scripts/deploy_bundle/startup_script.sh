#!/usr/bin/env bash
set -euo pipefail

# Expect docker-compose.yml, .env.template, and this script in ONE folder with `docker compose`.
#
# Writes `.env` from Doppler then runs Compose here (`doppler setup` once in this directory).
#
# Alternate (no `.env` on disk):  doppler run -- docker compose up --pull always -d
#
# Usage:
#   ./startup_script.sh                    → up --pull always -d
#   ./startup_script.sh up --pull always   → omit -d to stream logs locally

export BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BUNDLE_DIR"

tmp="$(mktemp "${TMPDIR:-/tmp}/discord-bot-docker-.env.XXXXXX")"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

doppler secrets download --format env "$tmp"
mv "$tmp" .env
trap - EXIT
chmod 600 .env || true

if [[ $# -eq 0 ]]; then
	set -- up --pull always -d
fi
exec docker compose "$@"
