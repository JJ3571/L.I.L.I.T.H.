#!/usr/bin/env bash
set -euo pipefail

# Run Docker Compose with secrets from your active Doppler project/config for this directory.
# Compose substitutes `${DATABASE_URL}`, etc. from the **process environment** — `doppler run`
# injects decrypted values, so you do not need a repo-root `.env` for interpolation.
#
# Use this when `doppler secrets download --format env` is not plain `KEY=value` (e.g. some
# configs or CLI/API paths yield ciphertext like `4:base64:...` in the file — Compose cannot
# parse that). `doppler run` always resolves secrets the same way the CLI does for execution.
#
# Optional plaintext `.env` in the compose directory is still read by Compose for any keys you
# keep only on disk; prefer not committing secrets.
#
# Alternative: put secrets only in `.env` and run `docker compose up` directly (no Doppler).
#
# Passing only `DOPPLER_TOKEN=… docker compose up` does **not** inject app secrets.
#
# Requires: doppler CLI configured for this repo (e.g. `doppler configure` or `doppler.yaml`).
#
# Usage:
#   ./scripts/docker_compose_up.sh
#       → doppler run -- docker compose up --pull always (default when no args)
#   ./scripts/docker_compose_up.sh up --pull always -d
#   ./scripts/docker_compose_up.sh logs -f bot
#
# Repo root: parent of scripts/ when this file lives under scripts/;
# otherwise the directory containing this script (so a repo-root copy still works).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "$SCRIPT_DIR")" == "scripts" ]]; then
	REPO_ROOT="$(dirname "$SCRIPT_DIR")"
else
	REPO_ROOT="$SCRIPT_DIR"
fi
cd "$REPO_ROOT"

if [[ $# -eq 0 ]]; then
	set -- up --pull always
fi
exec doppler run -- docker compose "$@"
