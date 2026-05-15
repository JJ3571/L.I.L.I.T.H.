#!/usr/bin/env bash
#
# Maintainer VPS entrypoint (paths under /home/discord_bot). After cloning the repo,
# use scripts/run_bot_doppler.sh or scripts/run_bot_env.sh instead — see CONTRIBUTING.md.
#
# Hardcoded method since Doppler/UV is being a pain
set -euo pipefail
# systemd uses a pipe for stdout — without this, Python may buffer boot_print lines for a long time.
export PYTHONUNBUFFERED=1
cd /home/discord_bot
exec /usr/bin/doppler run -- /home/discord_bot/.local/bin/uv run python -m main_bot "$@"

# Original method:
# set -euo pipefail
# cd "$(dirname "$0")/.."
# exec doppler run -- uv run python -m main_bot "$@"
