#!/usr/bin/env bash
set -euo pipefail

# Refresh repo-root `.env` from your active Doppler project/config for this directory,
# then invoke Docker Compose. `.env` is gitignored — do not commit it.
#
# Compose substitutes ${DATABASE_URL}, etc. from that `.env` into container env — no need
# for `env_file:` when using this workflow.
#
# Alternative (no `.env` on disk): `doppler run -- docker compose up --pull always`
# Passing only `DOPPLER_TOKEN=… docker compose up` does **not** inject app secrets.
#
# Requires: doppler CLI configured for this repo (e.g. `doppler configure` or a
# `doppler.yaml` / scoped settings). Same project/config `doppler run` would use here.
#
# Usage:
#   ./scripts/docker_compose_up.sh
#       → docker compose up --pull always (default when no args)
#   ./scripts/docker_compose_up.sh up --pull always -d
#   ./scripts/docker_compose_up.sh logs -f bot
#
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

tmp="$(mktemp "${TMPDIR:-/tmp}/discord-bot-docker-.env.XXXXXX")"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

doppler secrets download --format env "$tmp"
mv "$tmp" .env
trap - EXIT
chmod 600 .env || true

if [[ $# -eq 0 ]]; then
	set -- up --pull always
fi
exec docker compose "$@"
