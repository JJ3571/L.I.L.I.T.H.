#!/usr/bin/env bash
# Pack a ZIP + unpacked folder under dist/ — no duplicate compose/env in-repo.
#
# Copies from canonical repo files:
#   docker-compose.yml     (YAML from `services:` onward; header overlay for ZIP users)
#   .env.example           → bundle/.env.template
#   lavalink/application.yml.example
#   scripts/deploy_bundle/{README.md,startup_script.sh,docker_deploy.sh}
#   (startup/docker_deploy flags align with scripts/run_bot.sh: --doppler | --env, optional --dir)
#
# Usage:
#   ./scripts/build_deploy_bundle.sh           # writes dist/discord-bot-standalone/ + .zip

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_REL="${BUNDLE_REL:-discord-bot-standalone}"
OUT="$ROOT/dist/$BUNDLE_REL"
HDR="$ROOT/scripts/deploy_bundle/docker-compose.bundle-header.frag"

rm -rf "$OUT"
mkdir -p "$OUT/lavalink"

{
	cat "$HDR"
	awk '/^services:/{seen=1} seen' "$ROOT/docker-compose.yml"
} >"$OUT/docker-compose.yml"

cp "$ROOT/.env.example" "$OUT/.env.template"
cp "$ROOT/lavalink/application.yml.example" "$OUT/lavalink/application.yml.example"
cp "$ROOT/scripts/deploy_bundle/README.md" "$OUT/README.md"
cp "$ROOT/scripts/deploy_bundle/startup_script.sh" "$OUT/startup_script.sh"
cp "$ROOT/scripts/deploy_bundle/docker_deploy.sh" "$OUT/docker_deploy.sh"
chmod +x "$OUT/startup_script.sh" "$OUT/docker_deploy.sh"

ZIP="$ROOT/dist/${BUNDLE_REL}.zip"
rm -f "$ZIP"
( cd "$ROOT/dist" && zip -rq "$(basename "$ZIP")" "$(basename "$OUT")" )

echo "Wrote $OUT"
echo "Wrote $ZIP"
