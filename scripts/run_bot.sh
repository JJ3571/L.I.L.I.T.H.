#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec doppler run -- uv run python -m main_bot "$@"
