# VPS deployment for GitHub Actions CI/CD

This guide walks through **one full setup** so [`.github/workflows/main.yml`](../.github/workflows/main.yml) can run tests on GitHub, then **SSH into your server**, **pull the repo**, **sync dependencies with uv**, and **restart the bot**. It uses a generic Linux VPS (DigitalOcean droplet, Linode, Hetzner, AWS EC2, etc.)—the steps are the same; only the provider UI for creating the machine differs.

**Names used below** (replace with yours everywhere: server paths, systemd unit, workflow):

| Placeholder | Example in this repo |
|-------------|----------------------|
| `BOT_USER` | `discord_bot` |
| `REPO_PATH` | `/home/discord_bot_v2` |
| `SERVICE_NAME` | `discord_bot_v2` (systemd unit is often `SERVICE_NAME.service`) |

Edit the deploy **script** in `.github/workflows/main.yml` if your paths or user differ.

---

## How the pieces fit together (read this once)

You need **two different SSH keys** for two different connections:

1. **CI deploy key (GitHub Actions → your VPS)**  
   - Private key stored in GitHub secret `SSH_PRIVATE_KEY`.  
   - Public key in **`~/.ssh/authorized_keys` on the VPS** for whichever account you set as `SSH_USER` (often `root`).  
   - Purpose: let the workflow open an SSH session to run shell commands.

2. **Git deploy key (VPS → GitHub.com)**  
   - Key pair lives **on the server** under **`BOT_USER`** (e.g. `/home/discord_bot/.ssh/`).  
   - Public key added in **GitHub → your repository → Settings → Deploy keys** (read access is enough for `git fetch`).  
   - Purpose: let `sudo -u BOT_USER git fetch` authenticate to `git@github.com`.  
   - This is **not** the same key as `SSH_PRIVATE_KEY`. The Actions key never leaves GitHub’s runner except to SSH to your box; it does not authenticate to GitHub for `git`.

```mermaid
flowchart LR
  subgraph gha [GitHub_Actions]
    SK[SSH_PRIVATE_KEY]
  end
  subgraph vps [Your_VPS]
    AK[authorized_keys_for_SSH_USER]
    BU[BOT_USER_.ssh]
    GH[git_fetch_to_github.com]
  end
  subgraph gh [GitHub_com]
    REPO[Your_repo]
  end
  SK -->|SSH_session| AK
  BU -->|deploy_key| REPO
```

---

## 1. Create the VPS and log in

1. Create a small Ubuntu (or Debian) instance with a public IP and SSH allowed on port 22 (or your chosen port).
2. SSH in as root or the provider’s default user with the provider’s console or your own key.
3. Create **`BOT_USER`** if you want the bot to run as a non-root account (recommended):

   ```bash
   adduser --disabled-password --gecos "" discord_bot
   ```

   (Adjust `discord_bot` to your `BOT_USER`.)

4. Install base packages:

   ```bash
   apt update && apt install -y git curl
   ```

---

## 2. Install `uv` for `BOT_USER`

`uv` should be available where your deploy script calls it (this repo uses `/home/discord_bot/.local/bin/uv`).

```bash
sudo -u discord_bot bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

Confirm:

```bash
sudo -u discord_bot ~/.local/bin/uv --version
```

If you change install location, update the path in `.github/workflows/main.yml`.

---

## 3. Clone the repository as `BOT_USER`

Use the **same** `REPO_PATH` you will put in the workflow.

```bash
sudo mkdir -p "$(dirname /home/discord_bot_v2)"
sudo chown discord_bot:discord_bot /home/discord_bot  # parent if needed
sudo -u discord_bot git clone git@github.com:OWNER/REPO.git /home/discord_bot_v2
```

For the first clone you must already have **either** Git working as `BOT_USER` (deploy key, see section 6) **or** use HTTPS with a token once, then switch remotes.

Typical **SSH** remote:

```bash
sudo -u discord_bot git -C /home/discord_bot_v2 remote -v
# expect: git@github.com:OWNER/REPO.git
```

---

## 4. Doppler and systemd (runtime secrets)

The bot reads env from Doppler (or your chosen method). On the server:

1. Install/configure Doppler CLI and log in or use a service token where the unit runs.
2. Create a **systemd** unit that starts the bot, e.g.:

   ```ini
   [Service]
   ExecStart=/usr/bin/doppler run -- /home/discord_bot/.local/bin/uv run python -m main_bot
   WorkingDirectory=/home/discord_bot_v2
   User=discord_bot
   ```

   Or use [`scripts/run_bot.sh`](../scripts/run_bot.sh) inside `doppler run`.

3. `systemctl enable --now SERVICE_NAME` and confirm the bot runs.

---

## 5. Key A — SSH from GitHub Actions into the VPS (CI deploy key)

### 5.1 Generate a dedicated key pair **on your laptop** (do not reuse a personal key)

```bash
ssh-keygen -t ed25519 -f ./gha_vps_deploy -N ""
```

You get `gha_vps_deploy` (private) and `gha_vps_deploy.pub` (public).

### 5.2 Install the **public** key on the VPS for **`SSH_USER`**

- If **`SSH_USER` is `root`**:

  ```bash
  mkdir -p /root/.ssh
  chmod 700 /root/.ssh
  echo "CONTENTS_OF_gha_vps_deploy.pub" >> /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
  ```

- If **`SSH_USER` is `BOT_USER`**, use `/home/discord_bot/.ssh/authorized_keys` instead.

The **same** public key must not be confused with the Git deploy key in section 6—they are different key pairs.

### 5.3 Put the **private** key in GitHub

1. Repo → **Settings → Secrets and variables → Actions → New repository secret**  
2. Name: `SSH_PRIVATE_KEY`  
3. Value: paste the **entire** contents of `gha_vps_deploy` (including `BEGIN`/`END` lines).  
   - **Do not** add extra quotation marks around the whole key.  
   - Use real newlines (multiline paste is supported).

### 5.4 Other Action secrets

| Secret | Value |
|--------|--------|
| `SSH_HOST` | VPS public IP or DNS name |
| `SSH_USER` | Account whose `authorized_keys` you updated (e.g. `root`) |

Optional repository **variable**: `SSH_PORT` if SSH is not on 22.

### 5.5 Test from your laptop (same key GitHub will use)

```bash
ssh -i ./gha_vps_deploy -o IdentitiesOnly=yes root@YOUR_VPS_IP
```

If this fails, fix `authorized_keys` before relying on Actions.

---

## 6. Key B — `git fetch` from the VPS to GitHub (Git deploy key)

The workflow runs commands like `sudo -u BOT_USER git fetch`. That uses **`BOT_USER`’s** `~/.ssh/`, not root’s.

### 6.1 Create a key **on the VPS** as `BOT_USER`

```bash
sudo -u discord_bot mkdir -p /home/discord_bot/.ssh
sudo -u discord_bot chmod 700 /home/discord_bot/.ssh
sudo -u discord_bot ssh-keygen -t ed25519 -f /home/discord_bot/.ssh/github_deploy -N ""
sudo cat /home/discord_bot/.ssh/github_deploy.pub
```

### 6.2 Add the deploy key in GitHub

1. Open **that same repository** your `origin` points to (e.g. `OWNER/REPO`).  
2. **Settings → Deploy keys → Add deploy key**  
3. Title: e.g. `vps-readonly`  
4. Key: paste the **`.pub`** line  
5. Enable **Allow read access** (sufficient for `fetch` / `reset`)

### 6.3 Force SSH to use that key for `github.com`

Without this, OpenSSH looks for default `id_rsa` / `id_ed25519` and may find nothing.

```bash
sudo -u discord_bot tee /home/discord_bot/.ssh/config >/dev/null <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/github_deploy
  IdentitiesOnly yes
EOF
sudo chmod 600 /home/discord_bot/.ssh/config
sudo chown discord_bot:discord_bot /home/discord_bot/.ssh/config
```

### 6.4 Trust GitHub’s host key (recommended on the server)

```bash
sudo -u discord_bot ssh-keyscan -H github.com >> /home/discord_bot/.ssh/known_hosts
sudo chown discord_bot:discord_bot /home/discord_bot/.ssh/known_hosts
```

The workflow also sets `GIT_SSH_COMMAND` with `StrictHostKeyChecking=accept-new` for `git` so the first connection can succeed even before `known_hosts` exists; pinning `github.com` on the server is still good practice.

### 6.5 Verify

```bash
sudo -u discord_bot ssh -T git@github.com
# expect: successfully authenticated …

sudo -u discord_bot git -C /home/discord_bot_v2 fetch origin
```

---

## 7. `sudo` for deploy: `git` / `uv` as `BOT_USER`, restart as root

The example workflow SSHs as **`root`** (typical when Key A is in `/root/.ssh/authorized_keys`). Then:

- **`sudo -u discord_bot git …`** and **`sudo -u discord_bot … uv …`** keep the repo owned by `BOT_USER`.
- **`systemctl restart SERVICE_NAME`** runs as root without `sudo`.

If you SSH as `BOT_USER` instead, you need passwordless `sudo` for `systemctl` (narrow sudoers rule) or run the service as `BOT_USER` without `systemctl` (not covered here).

Example **sudoers** snippet (edit with `visudo`), only if needed:

```text
discord_bot ALL=(ALL) NOPASSWD: /bin/systemctl restart discord_bot_v2
```

---

## 8. Align `.github/workflows/main.yml` with your server

Open [`.github/workflows/main.yml`](../.github/workflows/main.yml) and check the **deploy** job `script:` block:

| What to verify | Your value |
|----------------|------------|
| `cd …` and `git` / `uv` paths | Must match `REPO_PATH` |
| `sudo -u …` | Must match `BOT_USER` |
| `uv` binary path | Must exist on the server |
| `systemctl restart …` | Must match your unit name |

This repo does **not** use repository variables `DEPLOY_PATH` / `SYSTEMD_SERVICE` in the workflow file; paths are **inline**. Change them here when you move providers or rename users.

---

## 9. `appleboy/ssh-action` notes (version 1.2.x)

- Valid inputs include `host`, `port`, `username`, `key`, `script`.  
- **`known_hosts` is not a valid input** for this version—GitHub Actions would warn and ignore it.  
- Optional **host pinning** for the **VPS** uses `fingerprint` (SHA256 of the server host key), not a full `known_hosts` blob. Only add if you wire `fingerprint:` in the workflow and a matching secret.

---

## 10. Troubleshooting quick reference

| Symptom | Likely cause |
|---------|----------------|
| `unable to authenticate` / `no supported methods remain` (Actions → VPS) | Wrong `SSH_USER`; public key not in **that** user’s `authorized_keys`; or private key in GitHub truncated / wrong / has passphrase |
| `Host key verification failed` for **github.com** during `git fetch` | `BOT_USER` missing `github.com` in `known_hosts`; workflow mitigates with `accept-new` |
| `Permission denied (publickey)` from **git@github.com** | No Git deploy key, or not added under **Repo → Deploy keys**, or missing `~/.ssh/config` `IdentityFile` |
| `Hi …! You've successfully authenticated` but `git fetch` still fails | Rare; check `origin` URL and repo name (fork vs upstream) |

**Diagnostic commands** (run on VPS as root; adjust paths):

```bash
REPO=/home/discord_bot_v2
sudo -u discord_bot git -C "$REPO" remote -v
sudo ls -la /home/discord_bot/.ssh/
sudo -u discord_bot ssh -o BatchMode=yes -T git@github.com
```

---

## 11. CI tests and Doppler on GitHub (optional)

If secret `DOPPLER_TOKEN` is set, the test job runs `doppler run -- uv run pytest`. Otherwise set placeholder env vars in the workflow (as in `main.yml`) or add a Doppler CI config and token per Doppler’s docs.

---

## 12. Checklist (new provider / new server)

Use this when you rebuild the VPS or switch cloud:

- [ ] VPS created; firewall allows SSH (and bot ports if needed)
- [ ] `BOT_USER` created; repo cloned at `REPO_PATH`
- [ ] `uv` installed for `BOT_USER`; systemd + Doppler + bot runs manually
- [ ] **Key A:** CI key pair; public in `SSH_USER`’s `authorized_keys`; private in `SSH_PRIVATE_KEY`; `SSH_HOST`, `SSH_USER` set
- [ ] **Key B:** `BOT_USER` deploy key; public in GitHub **Deploy keys**; `~/.ssh/config` with `IdentityFile`; `known_hosts` for `github.com` (optional with workflow `accept-new`)
- [ ] Local test: `ssh -i ci_private_key SSH_USER@SSH_HOST` and `sudo -u BOT_USER git fetch` both succeed
- [ ] `.github/workflows/main.yml` deploy script paths and `systemctl` name updated
- [ ] Push to `main` and confirm Actions: test job green, deploy job green

---

## Related files

- [`.github/workflows/main.yml`](../.github/workflows/main.yml) — CI + deploy commands  
- [`scripts/run_bot.sh`](../scripts/run_bot.sh) — local/VPS wrapper with `doppler run`
