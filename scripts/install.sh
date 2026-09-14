#!/usr/bin/env bash
#
# First-time install for a Docker Compose deployment (no git clone required).
#
# Downloads docker-compose.yml, .env.example, and the Lavalink config template.
# Creates logs/ and local_audio/. Copies templates to working files when missing.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JJ3571/L.I.L.I.T.H./main/scripts/install.sh | bash
#   ./scripts/install.sh
#   INSTALL_DIR=/opt/discord-bot ./scripts/install.sh
#
# Env overrides:
#   INSTALL_DIR   Target directory (default: current directory)
#   REPO          GitHub owner/repo (default: JJ3571/L.I.L.I.T.H.)
#   REF           Git ref (default: main)

set -euo pipefail

REPO="${REPO:-JJ3571/L.I.L.I.T.H.}"
REF="${REF:-main}"
INSTALL_DIR="${INSTALL_DIR:-.}"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${REF}"

fetch() {
	local rel="$1"
	local dest="$2"
	local url="${BASE_URL}/${rel}"
	echo "Downloading ${rel} → ${dest}"
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL "$url" -o "$dest"
	elif command -v wget >/dev/null 2>&1; then
		wget -qO "$dest" "$url"
	else
		echo "install.sh: curl or wget is required." >&2
		exit 1
	fi
}

mkdir -p "$INSTALL_DIR"
INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
cd "$INSTALL_DIR"

mkdir -p logs local_audio/music lavalink scripts

fetch "docker-compose.yml" "docker-compose.yml"
fetch ".env.example" ".env.example"
fetch "lavalink/application.yml.example" "lavalink/application.yml.example"
fetch "scripts/bot.sh" "scripts/bot.sh"
chmod +x scripts/bot.sh

if [[ ! -f .env ]]; then
	cp .env.example .env
	echo "Created .env from .env.example"
else
	echo ".env already exists — left unchanged"
fi

if [[ ! -f lavalink/application.yml ]]; then
	cp lavalink/application.yml.example lavalink/application.yml
	echo "Created lavalink/application.yml"
else
	echo "lavalink/application.yml already exists — left unchanged"
fi

cat <<EOF

Install complete in: ${INSTALL_DIR}

Next steps:
  1. Edit .env. Set DISCORD_BOT_TOKEN, APPLICATION_ID, and GUILD_ID.
  2. Leave DATABASE_URL empty to use the bundled Postgres (default).
  3. Start the stack:
       ./scripts/bot.sh doctor
       ./scripts/bot.sh up
       ./scripts/bot.sh logs

See docs/QUICKSTART.md for the full procedure.
EOF
