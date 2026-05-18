#!/usr/bin/env bash
#
# Cloned-repo Docker Compose entrypoint: runs Compose from `.docker-local-build/` against a
# locally built bot image (see scripts/local_docker_build.sh). Secrets: `doppler run` (--doppler)
# or the staged `.env` only (--env). Flag semantics align with scripts/run_bot.sh.
#
# If `.docker-local-build/` is missing the compose files, runs `local_docker_build.sh prepare` first.
#
# Compose substitutes ${VAR} from the staging `.env` and/or Doppler-injected process env (--doppler).
#
# Requires: Docker daemon for compose commands. --doppler also needs the Doppler CLI for this repo.
#
# Usage:
#   ./scripts/docker_compose_up.sh                              → --doppler; prepare if needed; up --build -d
#   ./scripts/docker_compose_up.sh --env                        → compose only (needs staging .env)
#   ./scripts/docker_compose_up.sh --env up --build             → foreground / custom flags
#   ./scripts/docker_compose_up.sh logs -f bot
#
# Override staging dir: --dir / --workdir, DOCKER_LOCAL_BUILD_WORKDIR, or legacy DOCKER_LOCAL_IMAGE_TEST_WORKDIR

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
	cat >&2 <<'EOF'
Usage: docker_compose_up.sh [--doppler|--env] [--dir DIR|-C DIR|--workdir DIR|-w DIR] [--] [docker compose args]

  --doppler    Run: doppler run -- docker compose … (default). Secrets inject at runtime.
  --env        Run docker compose only; requires `.docker-local-build/.env` (after prepare).
  --dir, -C    Staging directory (same as --workdir / -w). Overrides DOCKER_LOCAL_BUILD_WORKDIR for this run.

If no compose args are given, defaults to: up --build -d

EOF
}

WORKDIR="${DOCKER_LOCAL_BUILD_WORKDIR:-${DOCKER_LOCAL_IMAGE_TEST_WORKDIR:-$REPO/.docker-local-build}}"
MODE=""
WORKDIR_CLI=""
PASS=()
while [[ $# -gt 0 ]]; do
	case "$1" in
		--doppler)
			if [[ -n "$MODE" && "$MODE" != doppler ]]; then
				echo "docker_compose_up.sh: use only one of --doppler or --env" >&2
				exit 1
			fi
			MODE=doppler
			shift
			;;
		--env)
			if [[ -n "$MODE" && "$MODE" != env ]]; then
				echo "docker_compose_up.sh: use only one of --doppler or --env" >&2
				exit 1
			fi
			MODE=env
			shift
			;;
		--dir|-C|--workdir|-w)
			if [[ $# -lt 2 ]]; then
				echo "docker_compose_up.sh: $1 requires a directory" >&2
				exit 1
			fi
			WORKDIR_CLI="$2"
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

MODE="${MODE:-doppler}"

if [[ -n "$WORKDIR_CLI" ]]; then
	WORKDIR="$WORKDIR_CLI"
fi

if [[ ! -f "$WORKDIR/docker-compose.yml" || ! -f "$WORKDIR/docker-compose.local-build.yml" ]]; then
	echo "[docker_compose_up] Staging missing — running local_docker_build.sh prepare …" >&2
	if [[ -n "$WORKDIR_CLI" ]]; then
		"$SCRIPT_DIR/local_docker_build.sh" --workdir "$WORKDIR_CLI" prepare
	else
		"$SCRIPT_DIR/local_docker_build.sh" prepare
	fi
fi

if [[ "$MODE" == env && ! -f "$WORKDIR/.env" ]]; then
	echo "docker_compose_up.sh: --env requires $WORKDIR/.env (run prepare once or copy from .env.example)." >&2
	exit 1
fi

if [[ ${#PASS[@]} -eq 0 ]]; then
	PASS=(up --build -d)
fi

COMPOSE=(
	docker compose --project-directory "$WORKDIR"
	-f "$WORKDIR/docker-compose.yml"
	-f "$WORKDIR/docker-compose.local-build.yml"
	"${PASS[@]}"
)

if [[ "$MODE" == doppler ]]; then
	exec doppler run -- "${COMPOSE[@]}"
else
	exec "${COMPOSE[@]}"
fi
