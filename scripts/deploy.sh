#!/usr/bin/env bash
# Deploy discord-bot via Docker, fetching secrets from Doppler at runtime.
# No .env file is written to disk — Doppler injects env vars directly to the
# container on every start.
#
# Usage:
#   ./scripts/deploy.sh          # deploy latest main (pull + up)
#   ./scripts/deploy.sh --build  # rebuild image before deploying
#   ./scripts/deploy.sh --pull   # only pull latest image
#
# Requirements:
#   - doppler CLI logged in (doppler login)
#   - docker & docker compose installed
#   - ghcr.io packages accessible (logged in via `echo "$GHCR_TOKEN" | docker login ghcr.io -u JJ3571 ...`)
#
# On the VPS, set these environment variables (e.g. in ~/.bashrc or systemd env):
#   export DOPPLER_PROJECT=discord-bot
#   export DOPPLER_CONFIG=production  # or staging
#   export GHCR_TOKEN=<github-pat-with-package-read-scope>
#   export VERSION=latest  # optional, defaults to 'latest'

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Parse flags
DO_BUILD=false
DO_PULL=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)  DO_BUILD=true; shift ;;
    --pull)   DO_PULL=true;  shift ;;
    *)        echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

VERSION="${VERSION:-latest}"
IMAGE_BOT="ghcr.io/jj3571/discord-bot:${VERSION}"
IMAGE_LAVALINK="ghcr.io/jj3571/lavalink:${VERSION}"

echo "=== Discord Bot Deploy (Doppler) ==="
echo "  Bot image:      $IMAGE_BOT"
echo "  Lavalink image: $IMAGE_LAVALINK"
echo ""

# Ensure GHCR auth
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u JJ3571 --password-stdin 2>/dev/null || true
fi

# Pull latest images (unless --build only)
if [[ "$DO_PULL" == "true" || "$DO_BUILD" == "false" ]]; then
  echo "[1/3] Pulling latest images..."
  docker pull "$IMAGE_BOT"       || echo "Warning: bot image pull failed (may not exist yet)"
  docker pull "$IMAGE_LAVALINK"  || echo "Warning: lavalink image pull failed (may not exist yet)"
fi

# Build (optional)
if [[ "$DO_BUILD" == "true" ]]; then
  echo "[2/3] Building bot image..."
  docker build -t "$IMAGE_BOT" "$REPO_ROOT"
fi

# Start services with Doppler injecting env vars
echo "[3/3] Starting services (Doppler)..."
doppler run -- docker compose up -d

echo ""
echo "Done. Check status with: docker compose ps"
echo "Logs: docker compose logs -f bot"