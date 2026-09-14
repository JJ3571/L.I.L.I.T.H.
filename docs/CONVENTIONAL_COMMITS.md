# Conventional commits

This repository does not enforce commit message format in CI. Conventional Commits is an optional style that keeps history and release notes readable.

See also [CONTRIBUTING.md](CONTRIBUTING.md) and the [Conventional Commits specification](https://www.conventionalcommits.org/).

## Shape

```text
<type>(optional scope): short description in imperative mood

Optional body with more detail.

Optional footer(s): BREAKING CHANGE: ..., Fixes #123
```

- **Type** — kind of change. See the table below.
- **Scope** — optional area. Example: `feat(music): …`
- **Description** — short imperative phrase. Use “add” and “fix”, not “added” or “fixes”.
- **Body** — explain why or how. Wrap near 72 characters if you prefer a narrow log.

## Common types

| Type | Meaning | Example |
|------|---------|---------|
| `feat` | New user-facing behaviour | `feat(economy): add daily streak bonus` |
| `fix` | Bug fix | `fix(voice): reconnect when websocket drops` |
| `docs` | Documentation only | `docs: clarify quick start for Docker Compose` |
| `style` | Formatting only | `style: ruff format crafty_controller` |
| `refactor` | Internal change, same outward behaviour | `refactor: extract playlist loader helper` |
| `perf` | Performance improvement | `perf(db): index wallet lookups by guild` |
| `test` | Add or fix tests | `test: cover admin toggle reload path` |
| `build` | Build system or packaging | `build: pin Dockerfile base image digest` |
| `ci` | CI configuration | `ci: run pytest with Postgres service` |
| `chore` | Other maintenance | `chore: bump lockfile for security advisory` |

Use `revert:` for reverts when you follow the specification format.

## Breaking changes

If callers, config, database schema, or Discord contracts change in an incompatible way, mark the commit.

```text
feat!: remove legacy /xp slash command

BREAKING CHANGE: Use /economy balance instead. The xp table is dropped.
```

The `!` after the type signals a break. The `BREAKING CHANGE:` footer explains the migration.

## Examples

Good:

```text
fix: handle missing LAVALINK_URI without crashing on startup

feat(music): add queue shuffle slash command

docs(config): document BOT_LOG_FILE for Compose mounts

chore: tighten SSH deploy directory checks in workflow

ci: skip closed unmerged PR runs for deploy

test(brainrot): assert sticker cooldown respects guild setting
```

Avoid vague one-liners:

```text
bad:  updates
bad:  misc fixes
better: fix(logging): rotate discord_bot.log when size exceeds cap
```

Squash-merge titles often mirror the pull request title. A `feat:` or `fix:` prefix helps release note grouping.

## Relation to semver

Rough mapping:

- `fix` → often patch
- `feat` → often minor
- `BREAKING CHANGE` or `feat!` → major

`chore`, `docs`, and `ci` alone usually do not require a release. Maintainers pick patch, minor, or major in `./scripts/tag_release.sh`.
