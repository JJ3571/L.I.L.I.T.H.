#!/usr/bin/env bash
# Run Lavalink from this repo for local development.
#
# Uses ``$JAVA_HOME/bin/java`` when JAVA_HOME is set; otherwise ``java`` from PATH.
# macOS (Temurin/etc.): export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
#
# 1. Drop ``Lavalink.jar`` (or exactly one other Lavalink ``*.jar``) here — tracked filenames vary by release.
# 2. cp application.yml.example application.yml   (edit password/port if needed)
# 3. ./lavalink/run-local.sh
#
# Match lavalink.server.password in application.yml with bot LAVALINK_PASSWORD / LAVALINK_URI.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [[ ! -f application.yml ]]; then
  echo "Missing lavalink/application.yml — copy lavalink/application.yml.example and edit if needed." >&2
  exit 1
fi

JAR=""
shopt -s nullglob
lav=( Lavalink*.jar )
ones=( ./*.jar )
shopt -u nullglob

if [[ -f Lavalink.jar ]]; then
  JAR="Lavalink.jar"
elif (( ${#lav[@]} == 1 )) && [[ -f "${lav[0]}" ]]; then
  JAR="${lav[0]#./}"
elif (( ${#ones[@]} == 1 )) && [[ -f "${ones[0]}" ]]; then
  JAR="${ones[0]#./}"
fi

if [[ -z "$JAR" ]] || [[ ! -f "$JAR" ]]; then
  echo "No runnable Lavalink jar found in lavalink/. Prefer Lavalink.jar or exactly one *.jar here." >&2
  exit 1
fi

if [[ -z "${JAVA_OPTS-}" ]]; then
  JAVA_OPTS="-Xmx512M"
fi

JAVA_BIN="java"
if [[ -n "${JAVA_HOME-}" ]] && [[ -x "${JAVA_HOME}/bin/java" ]]; then
  JAVA_BIN="${JAVA_HOME}/bin/java"
fi

echo "Starting Lavalink using ${JAR} (${JAVA_OPTS}), JVM: $("${JAVA_BIN}" -version 2>&1 | head -n 1)"
# shellcheck disable=SC2086
exec "${JAVA_BIN}" ${JAVA_OPTS} -jar "$JAR"
