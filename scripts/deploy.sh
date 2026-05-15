#!/usr/bin/env bash
#
# Convenience deploy for cloned repositories (compose lives at repo root with ./local_audio here).
#
# VPS users without a repo clone should use **`discord-bot-standalone.zip`** from GitHub Releases
# (see README inside that ZIP — `scripts/deploy_bundle/README.md` in the repository).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

docker compose down
exec "$SCRIPT_DIR/docker_compose_up.sh" up --pull always -d
