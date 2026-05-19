#!/usr/bin/env bash
#
# Materialize `.docker-local-build/` for cloning contributors: copy root docker-compose.yml,
# rewrite bind-mount paths to repo-root local_audio/, lavalink/, logs/, and emit
# docker-compose.local-build.yml (local Dockerfile build only).
#
# Bare-metal parity: edit Lavalink config and audio under the repo tree — Compose uses the same paths.
#
# Usage:
#   ./scripts/local_docker_build.sh prepare           # dirs + YAML + .env only (no Docker)
#   ./scripts/local_docker_build.sh prepare-build     # prepare + docker compose build bot — no up
#
# Typical flow: `./scripts/docker_compose_up.sh` or `./scripts/docker_compose_up.sh --env`
# (runs prepare if missing). `--doppler` is the default (doppler run); `--env` uses staging `.env` only.
#
# Override staging dir:
#   --workdir PATH   or   DOCKER_LOCAL_BUILD_WORKDIR=PATH   (legacy: DOCKER_LOCAL_IMAGE_TEST_WORKDIR)

set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
  local_docker_build.sh [--workdir DIR] prepare
  local_docker_build.sh [--workdir DIR] prepare-build

Prepare writes `.docker-local-build/` under the repo by default:
  • docker-compose.yml — copy of repo root with ./local_audio, ./logs, ./lavalink paths → absolute repo paths
  • docker-compose.local-build.yml — build bot image from this repo’s Dockerfile (+ MUSIC_LOCAL_HTTP_*)
  • .env — first run only from repo `.env` or `.env.example` (+ Compose-network Lavalink + DATABASE_URL tweaks)

Environment:
  DOCKER_LOCAL_BUILD_WORKDIR       preferred staging directory
  DOCKER_LOCAL_IMAGE_TEST_WORKDIR  legacy fallback (same meaning)

Secrets: `./scripts/docker_compose_up.sh [--doppler|--env]` or maintain `.docker-local-build/.env` for `--env`.
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
	WORKDIR="${DOCKER_LOCAL_BUILD_WORKDIR:-${DOCKER_LOCAL_IMAGE_TEST_WORKDIR:-$REPO/.docker-local-build}}"
fi

DOCKER_COMPOSE=(
	docker compose --project-directory "$WORKDIR"
	-f "$WORKDIR/docker-compose.yml"
	-f "$WORKDIR/docker-compose.local-build.yml"
)

_rebuild_compose_argv() {
	DOCKER_COMPOSE=(
	docker compose --project-directory "$WORKDIR"
	-f "$WORKDIR/docker-compose.yml"
	-f "$WORKDIR/docker-compose.local-build.yml"
)
}

_lavalink_listen_for_docker() {
	local yaml="$1"
	if ! command -v python3 >/dev/null 2>&1; then
		echo "[local_docker_build] error: python3 is required to normalize lavalink/application.yml for Docker." >&2
		exit 1
	fi
	python3 - "$yaml" <<'PY'
import pathlib, re, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
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
	if grep -Eq '^LAVALINK_URI=http://127\.0\.0\.1:2333' "$envf" \
		|| grep -Eq '^LAVALINK_URI=http://localhost:2333' "$envf"; then
		perl -i -pe 's|^LAVALINK_URI=.*|LAVALINK_URI=http://lavalink:2333|' "$envf"
	fi
	if grep -Eq '^LAVALINK_DOCKER_URI=http://(127\.0\.0\.1|localhost):2333[[:space:]]*$' "$envf"; then
		perl -i -ne 'print unless /^LAVALINK_DOCKER_URI=http:\/\/(127\.0\.0\.1|localhost):2333\s*$/' "$envf"
	fi
}

# Bot container must reach Postgres via Compose DNS hostname ``postgres``, not loopback.
_env_database_url_for_compose_network() {
	local envf="$1"
	if [[ ! -f "$envf" ]]; then
		return 0
	fi
	if ! grep -Eq '^DATABASE_URL=' "$envf"; then
		return 0
	fi
	if ! grep -Eq '^DATABASE_URL=[^[:space:]]+@(127\.0\.0\.1|localhost):5432(/|\?|$|[[:space:]])' "$envf"; then
		return 0
	fi
	python3 - "$envf" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

def sub(m: re.Match[str]) -> str:
    val = m.group(1).strip()
    if not re.search(r"@(?:127\.0\.0\.1|localhost):5432(?=/|\?|$)", val, flags=re.I):
        return m.group(0)
    if val.startswith("postgresql+asyncpg://"):
        val = "postgresql://" + val[len("postgresql+asyncpg://") :]
    elif val.startswith("postgres://"):
        val = "postgresql://" + val[len("postgres://") :]
    val = re.sub(
        r"@(?:127\.0\.0\.1|localhost):5432(?=/|\?|$)",
        "@postgres:5432",
        val,
        count=1,
        flags=re.I,
    )
    return "DATABASE_URL=" + val

new, n = re.subn(r"(?m)^DATABASE_URL=(.+)$", sub, text)
if n:
    path.write_text(new, encoding="utf-8")
PY
}

_rewrite_bind_mounts_to_repo() {
	local compose_copy="$1"
	export LB_REPO="$REPO"
	perl -pi -e '
		my $r = $ENV{LB_REPO};
		$r =~ s{\\}{/}g;
		s{\./local_audio(?=:)}{$r/local_audio}g;
		s{\./logs(?=:)}{$r/logs}g;
		s{\./lavalink/application\.yml(?=:)}{$r/lavalink/application.yml}g;
	' "$compose_copy"
}

_emit_build_override() {
	REPO="$REPO" python3 - >"$WORKDIR/docker-compose.local-build.yml" <<'PY'
import json, os, pathlib

repo = pathlib.Path(os.environ["REPO"]).resolve()
ctx = json.dumps(str(repo))
print("# Generated by scripts/local_docker_build.sh — do not edit.")
print("services:")
print("  bot:")
print("    build:")
print(f"      context: {ctx}")
print("      dockerfile: Dockerfile")
print("    image: discord-bot-sandbox:local-docker-build")
print("    hostname: bot")
print("    environment:")
print("      MUSIC_LOCAL_HTTP_HOST: bot")
print('      MUSIC_LOCAL_HTTP_BIND_HOST: "0.0.0.0"')
PY
}

_require_docker() {
	if docker info >/dev/null 2>&1; then
		return 0
	fi
	cat >&2 <<'EOF'
local_docker_build: Docker does not appear to be running (or this user cannot reach the daemon).

Fix:
  • Start Docker Desktop / the Docker daemon, then rerun this script.
  • Linux: ensure your user can access the Docker socket or use sudo rootfully as appropriate.

This check runs only before docker compose commands; `prepare` does not require Docker.
EOF
	exit 1
}

prepare() {
	_rebuild_compose_argv
	mkdir -p "$REPO/local_audio" "$REPO/logs" "$REPO/lavalink"

	local lavalink_cfg="$REPO/lavalink/application.yml"
	if [[ ! -f "$lavalink_cfg" ]]; then
		cp "$REPO/lavalink/application.yml.example" "$lavalink_cfg"
		echo "[local_docker_build] Created $lavalink_cfg from application.yml.example — edit passwords/plugins as needed." >&2
	fi
	_lavalink_listen_for_docker "$lavalink_cfg"

	mkdir -p "$WORKDIR"
	cp "$REPO/docker-compose.yml" "$WORKDIR/docker-compose.yml"
	_rewrite_bind_mounts_to_repo "$WORKDIR/docker-compose.yml"
	_emit_build_override

	local env_dst="$WORKDIR/.env"
	if [[ ! -f "$env_dst" ]]; then
		if [[ -f "$REPO/.env" ]]; then
			cp "$REPO/.env" "$env_dst"
			_env_lavalink_uri_for_compose_network "$env_dst"
			_env_database_url_for_compose_network "$env_dst"
			echo "[local_docker_build] Created $env_dst from repo .env (+ LAVALINK_* / DATABASE_URL Compose tweaks if needed)." >&2
		else
			cp "$REPO/.env.example" "$env_dst"
			_env_lavalink_uri_for_compose_network "$env_dst"
			_env_database_url_for_compose_network "$env_dst"
			echo "[local_docker_build] Created $env_dst from .env.example — edit secrets before relying on prod data." >&2
		fi
	else
		echo "[local_docker_build] Keeping existing $env_dst (Compose files refreshed)." >&2
	fi

	echo "[local_docker_build] Local Compose layout ready at:" >&2
	echo "  $WORKDIR" >&2
	echo "[local_docker_build] Repo bind mounts: local_audio/, lavalink/application.yml, logs/" >&2
	echo "[local_docker_build] Next: ./scripts/docker_compose_up.sh   or   ./scripts/local_docker_build.sh prepare-build" >&2
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
		echo "[local_docker_build] docker compose build bot (containers not started) …" >&2
		(cd "$WORKDIR" && "${DOCKER_COMPOSE[@]}" build bot)
		echo "[local_docker_build] Build complete. Bring up Lavalink + bot with ./scripts/docker_compose_up.sh" >&2
		exit 0
	fi

	echo "error: unknown arguments — use prepare or prepare-build (see --help)." >&2
	exit 2
}

main "$@"
