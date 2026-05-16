# Conventional commits (optional style guide)

This repository does **not** enforce commit message format in CI. **[Conventional Commits](https://www.conventionalcommits.org/)** is a lightweight convention many teams use so history, release notes, and semver guesses stay readable. Aligning with it when you write messages is enough—no extra tooling required unless you adopt something like Release Please later.

---

## Shape

```
<type>(optional scope): short description in imperative mood

Optional body with more detail.

Optional footer(s): BREAKING CHANGE: ..., Fixes #123, etc.
```

- **Type** — what kind of change this is (see table below).
- **Scope** — optional narrow area: `feat(music): …`, `fix(ci): …`.
- **Description** — ~50 chars; present tense / imperative (“add”, “fix”, not “added”, “fixes”).
- **Body** — _why_ or _how_, wraps at ~72 chars if you care about `git log` width.

---

## Common types

| Type | Meaning | Example |
|------|---------|---------|
| **feat** | New user-facing behavior | `feat(economy): add daily streak bonus` |
| **fix** | Bug fix (backward compatible) | `fix(voice): reconnect when websocket drops` |
| **docs** | Documentation only | `docs: clarify Doppler setup in README` |
| **style** | Formatting, no logic change (not CSS) | `style: ruff format craftyg_controller` |
| **refactor** | Internal change, same outward behavior | `refactor: extract playlist loader helper` |
| **perf** | Performance improvement | `perf(db): index wallet lookups by guild` |
| **test** | Adding or fixing tests | `test: cover admin toggle reload path` |
| **build** | Build system or packaging | `build: pin Dockerfile base image digest` |
| **ci** | CI configuration | `ci: run pytest with Postgres service` |
| **chore** | Maintenance that isn’t feat/fix/docs | `chore: bump lockfile for security advisory` |

Use **`revert:`** for reverts if you follow the spec’s revert format.

---

## Breaking changes

If callers, config, database schema, or Discord-facing contracts change in an incompatible way:

**Option A — footer (spec style)**

```
feat!: remove legacy /xp slash command

BREAKING CHANGE: Use /economy balance instead; xp table dropped.
```

The **`!`** after `feat` is a shorthand signal; the **`BREAKING CHANGE:`** footer explains what to do.

**Option B — separate commit**

Describe the break clearly in the body and bump **major** when you release (see [semver](https://semver.org/)).

---

## More examples

Good:

```
fix: handle missing LAVALINK_URI without crashing on startup

feat(music): add queue shuffle slash command

docs(doppler): document BOT_LOG_FILE for Compose mounts

chore: tighten SSH deploy directory checks in workflow

ci: skip closed unmerged PR runs for deploy

test(brainrot): assert sticker cooldown respects guild setting
```

Avoid vague one-liners when context matters:

```
bad:  updates
bad:  misc fixes
better: fix(logging): rotate discord_bot.log when size exceeds cap
```

Squash-merge titles often mirror the PR title—using **`feat:` / `fix:`** there helps GitHub release note grouping too.

---

## Relation to semver & releases

Rough mapping (not legal advice):

- **`fix`** → often **patch**
- **`feat`** → often **minor**
- **`BREAKING CHANGE` / `feat!`** → **major**

**`chore` / `docs` / `ci`** alone usually **don’t require** a release unless you choose to ship docs or artifact updates with a patch anyway.

Maintainers who cut releases with **`./scripts/tag_release.sh`** pick **patch / minor / major** explicitly; conventional prefixes help that decision stay consistent.

---

## See also

- [Contributing](CONTRIBUTING.md) — PR flow, branches, releases  
- [Conventional Commits specification](https://www.conventionalcommits.org/)
