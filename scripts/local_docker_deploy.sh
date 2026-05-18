#!/usr/bin/env bash
#
# Cloned-repo Docker redeploy: docker compose down in `.docker-local-build/`, then
# scripts/docker_compose_up.sh with the same arguments (local image rebuild + up).
#
# Supports the same flags as docker_compose_up.sh (--doppler | --env, --dir / --workdir, compose args).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKDIR="${DOCKER_LOCAL_BUILD_WORKDIR:-${DOCKER_LOCAL_IMAGE_TEST_WORKDIR:-$REPO/.docker-local-build}}"

# Resolve staging dir from forwarded args so `down` hits the same tree as docker_compose_up.sh.
_FORWARD=("$@")
_WORKDIR_CLI=""
for ((_i = 0; _i < ${#_FORWARD[@]}; _i++)); do
	case "${_FORWARD[$_i]}" in
		--dir | -C | --workdir | -w)
			((_i + 1 < ${#_FORWARD[@]})) || {
				echo "local_docker_deploy.sh: ${_FORWARD[$_i]} requires a directory" >&2
				exit 1
			}
			_WORKDIR_CLI="${_FORWARD[$((_i + 1))]}"
			_i=$((_i + 1))
			;;
	esac
done
if [[ -n "$_WORKDIR_CLI" ]]; then
	WORKDIR="$_WORKDIR_CLI"
fi

if [[ -f "$WORKDIR/docker-compose.yml" && -f "$WORKDIR/docker-compose.local-build.yml" ]]; then
	docker compose --project-directory "$WORKDIR" \
		-f "$WORKDIR/docker-compose.yml" \
		-f "$WORKDIR/docker-compose.local-build.yml" \
		down
fi

exec env DOCKER_LOCAL_BUILD_WORKDIR="$WORKDIR" "$SCRIPT_DIR/docker_compose_up.sh" "$@"
