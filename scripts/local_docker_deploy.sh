#!/usr/bin/env bash
#
# Cloned-repo Docker redeploy: docker compose down in `.docker-local-build/`, then
# scripts/docker_compose_up.sh with the same arguments (local image rebuild + up).
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKDIR="${DOCKER_LOCAL_BUILD_WORKDIR:-${DOCKER_LOCAL_IMAGE_TEST_WORKDIR:-$REPO/.docker-local-build}}"

if [[ -f "$WORKDIR/docker-compose.yml" && -f "$WORKDIR/docker-compose.local-build.yml" ]]; then
	docker compose --project-directory "$WORKDIR" -f docker-compose.yml -f docker-compose.local-build.yml down
fi

exec "$SCRIPT_DIR/docker_compose_up.sh" "$@"
