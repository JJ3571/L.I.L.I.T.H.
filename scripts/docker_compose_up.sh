#!/usr/bin/env bash
#
# Cloned-repo Docker Compose entrypoint: runs Compose from `.docker-local-build/` against a
# locally built bot image (see scripts/local_docker_build.sh). Secrets via `doppler run`.
#
# If `.docker-local-build/` is missing the compose files, runs `local_docker_build.sh prepare` first.
#
# Compose substitutes ${VAR} from the staging `.env` and/or Doppler-injected process env.
#
# Requires: doppler CLI configured for this repo; Docker daemon for compose commands.
#
# Usage:
#   ./scripts/docker_compose_up.sh                         → prepare if needed; up --build -d
#   ./scripts/docker_compose_up.sh up --build              → foreground / custom flags
#   ./scripts/docker_compose_up.sh logs -f bot
#
# Override staging dir: DOCKER_LOCAL_BUILD_WORKDIR or legacy DOCKER_LOCAL_IMAGE_TEST_WORKDIR

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKDIR="${DOCKER_LOCAL_BUILD_WORKDIR:-${DOCKER_LOCAL_IMAGE_TEST_WORKDIR:-$REPO/.docker-local-build}}"

if [[ ! -f "$WORKDIR/docker-compose.yml" || ! -f "$WORKDIR/docker-compose.local-build.yml" ]]; then
	echo "[docker_compose_up] Staging missing — running local_docker_build.sh prepare …" >&2
	"$SCRIPT_DIR/local_docker_build.sh" prepare
fi

if [[ $# -eq 0 ]]; then
	set -- up --build -d
fi

exec doppler run -- docker compose --project-directory "$WORKDIR" -f docker-compose.yml -f docker-compose.local-build.yml "$@"
