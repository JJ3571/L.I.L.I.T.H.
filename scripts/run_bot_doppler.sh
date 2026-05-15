#!/usr/bin/env bash
# Run bot with secrets injected by the Doppler CLI (after `doppler setup` here).

set -euo pipefail
export PYTHONUNBUFFERED=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec doppler run -- uv run python -m main_bot "$@"
