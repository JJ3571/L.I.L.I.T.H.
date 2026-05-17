#!/usr/bin/env bash
#
# Bundle redeploy: docker compose down, then startup_script.sh with the same arguments.
# Flags (--doppler / --env / --dir) match scripts/run_bot.sh and startup_script.sh.
#

set -euo pipefail
export PYTHONUNBUFFERED=1

SCRIPT_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ORIG_ARGS=("$@")
DIR_OVERRIDE=""
i=0
n=${#ORIG_ARGS[@]}
while [[ $i -lt $n ]]; do
  case "${ORIG_ARGS[i]}" in
    --dir|-C)
      if [[ $((i + 1)) -ge $n ]]; then
        echo "docker_deploy.sh: ${ORIG_ARGS[i]} requires a directory" >&2
        exit 1
      fi
      DIR_OVERRIDE="${ORIG_ARGS[i + 1]}"
      i=$((i + 2))
      ;;
    *)
      i=$((i + 1))
      ;;
  esac
done

export BUNDLE_DIR="${DIR_OVERRIDE:-$SCRIPT_HOME}"
if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "docker_deploy.sh: not a directory: $BUNDLE_DIR" >&2
  exit 1
fi

cd "$BUNDLE_DIR"
docker compose down
exec "$BUNDLE_DIR/startup_script.sh" "${ORIG_ARGS[@]}"
