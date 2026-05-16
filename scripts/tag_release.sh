#!/usr/bin/env bash
#
# Interactive helper: choose semver bump (or custom), optionally sync pyproject.toml,
# commit, create annotated tag vX.Y.Z, and push to origin.
#
# Requires: git, a POSIX shell; perl is used for in-place pyproject.toml edits (macOS + Linux).
#
# Usage:
#   ./scripts/tag_release.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

die() {
	echo "tag_release: $*" >&2
	exit 1
}

prompt_yn() {
	local default="$1"
	local msg="$2"
	local hint=""
	local reply=""
	if [[ "$default" == "y" ]]; then
		hint=" [Y/n]"
	elif [[ "$default" == "n" ]]; then
		hint=" [y/N]"
	fi
	while true; do
		read -r -p "${msg}${hint}: " reply || true
		reply="$(echo "$reply" | tr '[:upper:]' '[:lower:]')"
		if [[ -z "$reply" ]]; then
			reply="$default"
		fi
		case "$reply" in
			y | yes) return 0 ;;
			n | no) return 1 ;;
			*) echo "Please answer y or n." ;;
		esac
	done
}

strip_v() {
	local t="$1"
	t="${t#v}"
	echo "$t"
}

latest_release_tag() {
	# Latest plain semver tag vX.Y.Z (excludes pre-release suffixes like v1.0.0-beta).
	git tag --list | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1
}

parse_semver() {
	local s="$1"
	if [[ ! "$s" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
		return 1
	fi
	echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}"
}

bump_semver() {
	local kind="$1"
	local major="$2"
	local minor="$3"
	local patch="$4"
	case "$kind" in
		patch) echo "$major.$minor.$((patch + 1))" ;;
		minor) echo "$major.$((minor + 1)).0" ;;
		major) echo "$((major + 1)).0.0" ;;
		*) die "unknown bump kind: $kind" ;;
	esac
}

pyproject_version_line() {
	grep -E '^version = "' pyproject.toml | head -1 | sed -E 's/^version = "([^"]+)".*/\1/'
}

set_pyproject_version() {
	local ver="$1"
	perl -pi -e 's/^version = "[^"]*"/version = "'"$ver"'"/' pyproject.toml
}

[[ -d .git ]] || die "run from repository root (no .git here)"

echo "Repository: $REPO_ROOT"
echo "Branch:     $(git branch --show-current 2>/dev/null || echo '(detached)')"

if [[ -n "$(git status --porcelain)" ]]; then
	echo ""
	echo "Warning: working tree is not clean:"
	git status --short
	echo ""
	prompt_yn n "Continue anyway (you should commit/stash unrelated changes first)" || exit 0
fi

LAST_TAG="$(latest_release_tag)"
if [[ -z "$LAST_TAG" ]]; then
	echo "No prior tag matching vX.Y.Z found."
	BASE_SEMVER="0.0.0"
	echo "Starting from logical base ${BASE_SEMVER} (first tag will be v0.0.1 unless you choose custom)."
else
	BASE_SEMVER="$(strip_v "$LAST_TAG")"
	echo "Latest release tag: ${LAST_TAG}"
fi

SEMVER_PARTS="$(parse_semver "$BASE_SEMVER")" || die "could not parse semver from tag baseline: ${BASE_SEMVER}"
read -r MAJOR MINOR PATCH <<<"$SEMVER_PARTS"

PATCH_NEXT="$(bump_semver patch "$MAJOR" "$MINOR" "$PATCH")"
MINOR_NEXT="$(bump_semver minor "$MAJOR" "$MINOR" "$PATCH")"
MAJOR_NEXT="$(bump_semver major "$MAJOR" "$MINOR" "$PATCH")"

echo ""
echo "Choose release bump:"
echo "  1) patch  (${LAST_TAG:-none} → v${PATCH_NEXT})"
echo "  2) minor  (${LAST_TAG:-none} → v${MINOR_NEXT})"
echo "  3) major  (${LAST_TAG:-none} → v${MAJOR_NEXT})"
echo "  4) custom (you type X.Y.Z, tag will be vX.Y.Z)"
echo ""
read -r -p "Enter choice [1-4]: " CHOICE

NEW_SEMVER=""
case "$CHOICE" in
	1) NEW_SEMVER="$PATCH_NEXT" ;;
	2) NEW_SEMVER="$MINOR_NEXT" ;;
	3) NEW_SEMVER="$MAJOR_NEXT" ;;
	4)
		read -r -p "Version (X.Y.Z only): " CUSTOM
		parse_semver "$CUSTOM" >/dev/null || die "invalid semver (use X.Y.Z)"
		NEW_SEMVER="$CUSTOM"
		;;
	*) die "invalid choice" ;;
esac

NEW_TAG="v${NEW_SEMVER}"

if git rev-parse -q --verify "refs/tags/${NEW_TAG}" >/dev/null 2>&1; then
	die "tag ${NEW_TAG} already exists locally"
fi

CUR_PY="$(pyproject_version_line || true)"
echo ""
echo "Planned:"
echo "  New tag:           ${NEW_TAG}"
echo "  pyproject.toml:    ${CUR_PY:-'(no version line?)'} → ${NEW_SEMVER}"

SYNC_PY=true
if ! prompt_yn y "Update pyproject.toml version to ${NEW_SEMVER}?"; then
	SYNC_PY=false
fi

PY_CHANGED=false
if [[ "$SYNC_PY" == true ]]; then
	if [[ "$CUR_PY" == "$NEW_SEMVER" ]]; then
		echo "pyproject.toml already at ${NEW_SEMVER}; no file edit."
	else
		set_pyproject_version "$NEW_SEMVER"
		PY_CHANGED=true
	fi
fi

DO_COMMIT=false
if [[ "$PY_CHANGED" == true ]]; then
	if prompt_yn y "Commit pyproject.toml with message 'chore: bump version to ${NEW_SEMVER}'?"; then
		DO_COMMIT=true
	fi
fi

if [[ "$PY_CHANGED" == true && "$DO_COMMIT" == false ]]; then
	if prompt_yn y "Revert pyproject.toml change and exit (no tag)?"; then
		git checkout -- pyproject.toml
		exit 0
	fi
	die "pyproject.toml modified but not committed; fix state manually before tagging."
fi

if [[ "$DO_COMMIT" == true ]]; then
	git add pyproject.toml
	git commit -m "chore: bump version to ${NEW_SEMVER}"
fi

if ! prompt_yn y "Create annotated git tag ${NEW_TAG}?"; then
	echo "Stopped before tagging."
	exit 0
fi

git tag -a "${NEW_TAG}" -m "Release ${NEW_TAG}"

echo ""
echo "Created tag ${NEW_TAG} at $(git rev-parse --short HEAD)"

if prompt_yn y "Push tag ${NEW_TAG} to origin?"; then
	git push origin "refs/tags/${NEW_TAG}"
fi

BR="$(git branch --show-current 2>/dev/null || true)"
if [[ -n "$BR" && "$DO_COMMIT" == true ]]; then
	if prompt_yn y "Push branch '${BR}' to origin (includes version bump commit)?"; then
		git push origin "${BR}"
	fi
fi

echo "Done."
