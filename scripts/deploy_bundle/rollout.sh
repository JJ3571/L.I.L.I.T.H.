#!/usr/bin/env bash
set -euo pipefail

export BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BUNDLE_DIR"

docker compose down
exec "$BUNDLE_DIR/startup_script.sh" "${@}"
