# Standalone Discord bot deployment folder

Everything you keep on the VPS (or workstation) sits **in one directory** next to **`docker-compose.yml`**.  

**Source of truth:** assembled from canonical files in [`Discord-Bot-Sandbox`](https://github.com/jj3571/Discord-Bot-Sandbox):

- **`docker-compose.yml`** — YAML body matches repo root **`docker-compose.yml`** (header may differ slightly for ZIP users).
- **`.env.template`** — copied from repo **`.env.example`** when the bundle was built (`cp .env.template .env` to edit offline).
- **`startup_script.sh` / `rollout.sh`** — from **`scripts/deploy_bundle/`** when the ZIP was assembled (maintainers edit those helpers in-repo; Compose + env stay single-source).

**Obtain:** download **`discord-bot-standalone.zip`** from the GitHub **Releases** page, or locally run `./scripts/build_deploy_bundle.sh` from the repository.

## Folder layout here

```
your-bot-dir/
├── docker-compose.yml
├── startup_script.sh
├── rollout.sh
├── README.md            # this file
├── .env.template        # reference only until you cp → .env
├── .env                 # secrets (never commit)
├── lavalink/
│   ├── application.yml           # REQUIRED (copy from application.yml.example)
│   └── application.yml.example   # bundled starter from the repo
├── logs/               # OPTIONAL but recommended — Docker maps `./logs:/app/logs` for `BOT_LOG_FILE` (default `discord_bot.log` inside)
└── local_audio/        # REQUIRED mount dir (may be empty)
```

The bot writes a **combined** rotating log (Nextcord + **`main_bot`**) under **`BOT_LOG_FILE`**. Compose defaults that to **`/app/logs/discord_bot.log`**; create **`logs/`** next to **`docker-compose.yml`** on the host so the file survives container restarts.

Set **`lavalink.server.password`** in **`application.yml`** to match **`LAVALINK_PASSWORD`** in `.env`/Doppler (the bundled example uses Spring placeholders). Optional YouTube OAuth: **`YOUTUBE_OAUTH_ENABLED`** / **`YOUTUBE_OAUTH_REFRESH_TOKEN`** on the **`lavalink`** service (see root **`docker-compose.yml`** and **`docs/DOPPLER_ENV_KEYS.md`**).

## Secrets

### A — Doppler

From **this deployment directory**:

```bash
doppler setup  # once, after doppler login
chmod +x startup_script.sh rollout.sh
./startup_script.sh    # doppler secrets download → .env, then compose up (--pull always -d)
```

Upgrades (`docker compose down` + startup again):

```bash
./rollout.sh
```

No `.env` file on disk: `doppler run -- docker compose up --pull always -d`.

### B — Manual `.env`

```bash
cp .env.template .env    # edit
docker compose up --pull always -d
```

If **GHCR** private for `ghcr.io/jj3571/discord-bot`:

```bash
echo "$GITHUB_PAT" | docker login ghcr.io -u YOUR_USERNAME --password-stdin
```

Lavalink image defaults to **`ghcr.io/lavalink-devs/lavalink`** (often public unless you substitute your own compose image).
