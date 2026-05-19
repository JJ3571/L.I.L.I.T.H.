#!/usr/bin/env bash
# Dump from SOURCE_DATABASE_URL (e.g. Neon) and restore into TARGET_DATABASE_URL (e.g. bundled/local Postgres).
# Requires libpq client tools (pg_dump / pg_restore) on PATH — same as postgres_dump_and_restore_helpers.py.
#
# Usage:
#   SOURCE_DATABASE_URL='postgresql://...neon...?sslmode=require' \
#   TARGET_DATABASE_URL='postgresql://bot:bot@127.0.0.1:5432/discord_bot' \
#   ./scripts/postgres_migrate_hosted_to_local.sh
#
set -euo pipefail

: "${SOURCE_DATABASE_URL:?Set SOURCE_DATABASE_URL to the hosted Postgres URL (e.g. Neon)}"
: "${TARGET_DATABASE_URL:?Set TARGET_DATABASE_URL to the destination URL}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DUMP="$(mktemp -t botpgdump.XXXXXX)"
cleanup() { rm -f "$DUMP"; }
trap cleanup EXIT

echo "[migrate] Dumping from SOURCE_DATABASE_URL …"
DATABASE_URL="$SOURCE_DATABASE_URL" uv run python scripts/postgres_dump_and_restore_helpers.py dump --output "$DUMP"

echo "[migrate] Restoring into TARGET_DATABASE_URL (--clean --if-exists) …"
DATABASE_URL="$TARGET_DATABASE_URL" uv run python scripts/postgres_dump_and_restore_helpers.py restore \
	--input "$DUMP" --clean --if-exists

echo "[migrate] Done."
echo "  • Point DATABASE_URL / Doppler at the target URL."
echo "  • Docker external-only: clear COMPOSE_PROFILES or omit bundled-db if Postgres is not in compose."
echo "  • Verify: uv run python admin_tools/verify_databases.py"
