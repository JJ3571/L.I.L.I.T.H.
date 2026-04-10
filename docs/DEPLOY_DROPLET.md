# One-time DigitalOcean droplet setup (CI/CD)

These steps prepare a droplet so [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) can deploy after tests pass on `main`.

## 1. Create user and SSH access

- Create a non-root user (for example `deploy`) with SSH key login.
- Generate an **ed25519** key pair used only for GitHub Actions. Add the **public** key to `~/.ssh/authorized_keys` on the droplet. Store the **private** key in GitHub as `SSH_PRIVATE_KEY`.
- On your machine, run `ssh-keyscan -H YOUR_DROPLET_IP_OR_HOST` and save the output to the GitHub secret `SSH_KNOWN_HOSTS`.

## 2. Install git, uv, and Doppler CLI

- Install `git` if missing.
- Install [uv](https://docs.astral.sh/uv/) (for example the official install script) so `uv` is on `PATH` for that user (`~/.local/bin` is already used in the workflow script).

## 3. Clone the repository

- Clone this repo to a fixed path (example: `/home/deploy/Discord-Bot-Sandbox`).
- Configure `origin` to your GitHub remote (HTTPS with credentials, or SSH with a **read-only** deploy key).

## 4. Systemd unit for the bot

- Create a systemd service whose `ExecStart` runs the bot under Doppler, for example:
  - `doppler run -- /path/to/uv run python -m main_bot`
  - or `doppler run -- /path/to/repo/scripts/run_bot.sh`
- Ensure Doppler is configured on the server (login or service token) so the unit can load secrets at runtime.

## 5. Allow `sudo systemctl restart` for the deploy user

- Prefer a **narrow** sudoers rule so only your bot unit can be restarted, for example:
  - `deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart your-bot.service`
- Match the unit name to the GitHub repository variable `SYSTEMD_SERVICE` (for example `discord-bot.service`).

## 6. Git “safe directory” (optional)

- The deploy script runs `git config --global --add safe.directory "$DEPLOY_PATH"` to avoid dubious ownership errors when the repo is owned by another user.

## 7. Configure GitHub Actions (repository)

**Secrets**

| Name | Purpose |
|------|--------|
| `SSH_PRIVATE_KEY` | Private key matching the droplet’s authorized_keys |
| `SSH_HOST` | Droplet hostname or IP |
| `SSH_USER` | SSH login user |
| `SSH_KNOWN_HOSTS` | Output of `ssh-keyscan -H ...` |

**Variables**

| Name | Purpose |
|------|--------|
| `DEPLOY_PATH` | Absolute path to the git clone on the droplet |
| `SYSTEMD_SERVICE` | systemd unit name (e.g. `discord-bot.service`) |
| `SSH_PORT` | Optional; SSH port if not 22 |

**Optional (CI tests with Doppler)**

| Name | Purpose |
|------|--------|
| `DOPPLER_TOKEN` | Service token; if set, tests run as `doppler run -- uv run pytest` |
| `DOPPLER_PROJECT` | Repository variable; required when using Doppler in CI unless `doppler.yaml` is committed |
| `DOPPLER_CONFIG` | Repository variable; Doppler config name (e.g. `ci`) |

If `DOPPLER_TOKEN` is not set, CI uses placeholder env vars and does not call Doppler.
