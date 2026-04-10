#!/usr/bin/env bash

# Hardcoded method since Doppler/UV is being a pain
set -euo pipefail
cd /home/discord_bot_v2
exec /usr/bin/doppler run -- /home/discord_bot/.local/bin/uv run python -m main_bot "$@"

# Original method:
# set -euo pipefail
# cd "$(dirname "$0")/.."
# exec doppler run -- uv run python -m main_bot "$@"
