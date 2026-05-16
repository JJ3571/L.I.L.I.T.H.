#!/usr/bin/env bash
#
# Spin up Docker Compose against a locally built bot image (same Dockerfile as CI/production),
# without touching GHCR defaults in the canonical docker-compose.yml.
#
# Writes a staging directory containing:
#   • docker-compose.yml (copy of repo root)
#   • docker-compose.local-build.yml (bot build.context → repo root, local image tag)
#   • lavalink/application.yml (repo lavalink/application.yml if present else application.yml.example;
#       staging copy normalizes server bind 127.0.0.1 → 0.0.0.0 and repairs one-line ``address``/``http2`` YAML damage
#   • local_audio/, logs/ (empty stubs; bind-mounted like production Compose)
#   • .env — first-run only: copied from repo .env if present, else .env.example with Compose-friendly
#       LAVALINK_URI / LAVALINK_DOCKER_URI staging tweaks (see _env_lavalink_uri_for_compose_network).
#
# Usage:
#   ./scripts/docker_compose_local_image_test.sh prepare           # dirs + YAML + .env only (no Docker)
#   ./scripts/docker_compose_local_image_test.sh prepare-build     # prepare + ``docker compose build bot`` — no ``up``
#   ./scripts/docker_compose_local_image_test.sh                   # prepare + ``docker compose up --build`` (bot + lavalink start)
#   ./scripts/docker_compose_local_image_test.sh up --build        # explicit compose up args
#
# Workdir defaults to repo-root `.docker-local-compose-test/` (gitignored). Override with:
#   --workdir PATH   or   DOCKER_LOCAL_IMAGE_TEST_WORKDIR=PATH
#
# Secrets / env: compose substitutes ${VAR} from staging `.env`. Use your real `.env`,
# `./scripts/docker_compose_up.sh` pattern (doppler run from repo root with same vars), or
# fill staging `.env` after `prepare`. The compose override pins Lavalink-facing HTTP to hostname `bot` and binds on
# 0.0.0.0 (see `MUSIC_LOCAL_HTTP_*` / `main_bot.server_configs.config`).

set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
  docker_compose_local_image_test.sh [--workdir DIR] prepare
  docker_compose_local_image_test.sh [--workdir DIR] prepare-build
  docker_compose_local_image_test.sh [--workdir DIR]              # equals: prepare then "docker compose up --build"
  docker_compose_local_image_test.sh [--workdir DIR] [DOCKER_COMPOSE_ARGS...]

Mode:
  prepare        Staging tree only (.docker-local-compose-test/ by default).
  prepare-build  Staging tree + builds the bot image; does NOT start containers ("docker compose up" is yours).
  (default args) Runs "docker compose up --build" — starts Lavalink then bot (depends_on lavalink starts first,
                 but the bot does not wait on Lavalink's health probe so both can rise without curl/JVM deadlock).

Environment:
  DOCKER_LOCAL_IMAGE_TEST_WORKDIR   default staging directory (same as --workdir)
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKDIR=""
while [[ "${1:-}" == --workdir || "${1:-}" == "-w" ]]; do
	if [[ "${2:-}" == "" ]]; then
		echo "error: ${1:-} expects a directory" >&2
		exit 2
	fi
	WORKDIR="${2:?}"
	shift 2
done

if [[ -z "${WORKDIR:-}" ]]; then
	WORKDIR="${DOCKER_LOCAL_IMAGE_TEST_WORKDIR:-$REPO/.docker-local-compose-test}"
fi

DOCKER_COMPOSE=(docker compose --project-directory "$WORKDIR" -f docker-compose.yml -f docker-compose.local-build.yml)

_rebuild_compose_argv() {
	DOCKER_COMPOSE=(docker compose --project-directory "$WORKDIR" -f docker-compose.yml -f docker-compose.local-build.yml)
}

_lavalink_listen_for_docker() {
	local yaml="$1"
	if ! command -v python3 >/dev/null 2>&1; then
		echo "[docker_compose_local_image_test] error: python3 is required to normalize lavalink/application.yml for Docker." >&2
		exit 1
	fi
	# Do not use line-based perl only: malformed YAML such as ``address: 0.0.0.0  http2:`` on one physical line breaks
	# Lavalink/Spring (symptom: Wavelink Pool.connect never registers a CONNECTED node).
	python3 - "$yaml" <<'PY'
import pathlib, re, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
# Split mistaken merge: address + http2 on the same physical line (editor/merge damage).
text = re.sub(
    r"^(\s*)address:\s*(.+?)\s+http2:\s*$",
    lambda m: f"{m.group(1)}address: {m.group(2).strip()}\n{m.group(1)}http2:",
    text,
    flags=re.MULTILINE,
)
lines = text.splitlines(keepends=True)
out: list[str] = []
for line in lines:
    if re.match(r"^(\s*)address:\s*127\.0\.0\.1\s*$", line.rstrip("\r\n")):
        indent = re.match(r"^(\s*)", line).group(1)
        newline = "\n" if line.endswith("\n") else ""
        out.append(f"{indent}address: 0.0.0.0{newline}")
    else:
        out.append(line)
path.write_text("".join(out), encoding="utf-8")
PY
}

_env_lavalink_uri_for_compose_network() {
	local envf="$1"
	if [[ ! -f "$envf" ]]; then
		return 0
	fi
	if grep -qx 'LAVALINK_URI=$' "$envf" || grep -qx 'LAVALINK_URI=' "$envf" || grep -qxE 'LAVALINK_URI=[[:space:]]*$' "$envf"; then
		perl -i -pe 's|^LAVALINK_URI=\s*|LAVALINK_URI=http://lavalink:2333|' "$envf"
		return 0
	fi
	# Only normalize obvious host-local URLs; preserve custom Compose/Lavalink hostnames otherwise.
	if grep -Eq '^LAVALINK_URI=http://127\.0\.0\.1:2333' "$envf" \
		|| grep -Eq '^LAVALINK_URI=http://localhost:2333' "$envf"; then
		perl -i -pe 's|^LAVALINK_URI=.*|LAVALINK_URI=http://lavalink:2333|' "$envf"
	fi
	# Compose bot service uses LAVALINK_DOCKER_URI for substitution (see repo docker-compose.yml). Strip useless loopback.
	if grep -Eq '^LAVALINK_DOCKER_URI=http://(127\.0\.0\.1|localhost):2333[[:space:]]*$' "$envf"; then
		perl -i -ne 'print unless /^LAVALINK_DOCKER_URI=http:\/\/(127\.0\.0\.1|localhost):2333\s*$/' "$envf"
	fi
}

_require_docker() {
	if docker info >/dev/null 2>&1; then
		return 0
	fi
	cat >&2 <<'EOF'
docker_compose_local_image_test: Docker does not appear to be running (or this user cannot reach the daemon).

Fix:
  • Start Docker Desktop / the Docker daemon, then rerun this script.
  • Linux: ensure your user can access the Docker socket or use sudo rootfully as appropriate.

This check runs only before docker compose commands; `prepare` does not require Docker.
EOF
	exit 1
}

prepare() {
	_rebuild_compose_argv
	mkdir -p "$WORKDIR/local_audio" "$WORKDIR/lavalink" "$WORKDIR/logs"
	cp "$REPO/docker-compose.yml" "$WORKDIR/docker-compose.yml"

	cat >"$WORKDIR/docker-compose.local-build.yml" <<EOF
# Generated by scripts/docker_compose_local_image_test.sh — do not edit in-repo copy.
services:
  bot:
    build:
      context: $REPO
      dockerfile: Dockerfile
    image: discord-bot-sandbox:local-compose-test
    hostname: bot
    environment:
      MUSIC_LOCAL_HTTP_HOST: bot
      MUSIC_LOCAL_HTTP_BIND_HOST: "0.0.0.0"
EOF

	local dst="$WORKDIR/lavalink/application.yml"
	if [[ -f "$REPO/lavalink/application.yml" ]]; then
		cp "$REPO/lavalink/application.yml" "$dst"
	else
		cp "$REPO/lavalink/application.yml.example" "$dst"
	fi
	# Always normalize server.bind for Compose + repair common one-line YAML damage (see function comment).
	_lavalink_listen_for_docker "$dst"

	local env_dst="$WORKDIR/.env"
	if [[ ! -f "$env_dst" ]]; then
		if [[ -f "$REPO/.env" ]]; then
			cp "$REPO/.env" "$env_dst"
			_env_lavalink_uri_for_compose_network "$env_dst"
			echo "[docker_compose_local_image_test] Created $env_dst from repo .env (+ LAVALINK_* staging tweaks for Compose if needed)." >&2
		else
			cp "$REPO/.env.example" "$env_dst"
			_env_lavalink_uri_for_compose_network "$env_dst"
			echo "[docker_compose_local_image_test] Created $env_dst from .env.example — edit secrets before relying on prod data." >&2
		fi
	else
		echo "[docker_compose_local_image_test] Keeping existing $env_dst" >&2
	fi

	echo "[docker_compose_local_image_test] Staging layout ready at:" >&2
	echo "  $WORKDIR" >&2
	echo "[docker_compose_local_image_test] Next — pick one:" >&2
	echo "  • prepare-build ··· build bot image only, then yourself: compose up from this dir" >&2
	echo "  • (default script / \"up\") ··· docker compose up (Lavalink + bot both start)." >&2
	printf '  %q ' "${DOCKER_COMPOSE[@]}"
	echo >&2
}

main() {
	if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
		usage
		exit 0
	fi

	if [[ "${1:-}" == prepare ]]; then
		prepare
		exit 0
	fi

	if [[ "${1:-}" == prepare-build ]]; then
		mkdir -p "$WORKDIR"
		prepare
		_require_docker
		echo "[docker_compose_local_image_test] docker compose build bot (containers not started) …" >&2
		(cd "$WORKDIR" && "${DOCKER_COMPOSE[@]}" build bot)
		echo "[docker_compose_local_image_test] Build complete. Bring up Lavalink + bot manually, for example:" >&2
		wq="$(printf '%q' "$WORKDIR")"
		echo "  cd $wq && docker compose -f docker-compose.yml -f docker-compose.local-build.yml up -d" >&2
		exit 0
	fi

	mkdir -p "$WORKDIR"
	prepare

	_require_docker

	[[ $# -gt 0 ]] || set -- up --build

	(cd "$WORKDIR" && "${DOCKER_COMPOSE[@]}" "$@")
}

main "$@"
