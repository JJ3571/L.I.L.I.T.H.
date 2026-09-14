# Music and Lavalink

This document describes Lavalink, local audio folders, and music-related environment keys. For the default Docker deploy, see [QUICKSTART.md](QUICKSTART.md). For secrets, see [CONFIGURATION.md](CONFIGURATION.md).

## Docker Compose (default)

The root `docker-compose.yml` runs a `lavalink` service from the official image. The bot connects to `http://lavalink:2333` on the Compose network.

1. Copy `lavalink/application.yml.example` to `lavalink/application.yml`.
2. Match `LAVALINK_PASSWORD` in `.env` to `lavalink.server.password` in that file.
3. Create `local_audio/` and `logs/` next to `docker-compose.yml`.
4. Start the stack with `./scripts/bot.sh up`.

The host `./logs` directory receives both `discord_bot.log` and `lavalink.log`.

## Local audio layout


| Path                               | Role                                                           |
| ---------------------------------- | -------------------------------------------------------------- |
| `local_audio/music/<folder>/`      | Flat folder for a slash command registered by `MUSIC_FOLDER_n` |
| `local_audio/music/gaming/<game>/` | Nested folders for `/gaming`                                   |
| `local_audio/brainrot/`            | Short sound effects for `/brainrot`                            |


Reserved folder names for `MUSIC_FOLDER_*`: `gaming` and `brainrot`.

### Register a music folder command

1. Place audio files under `local_audio/music/<name>/`.
2. Set `MUSIC_FOLDER_1=<name>` (or another free slot) in `.env`.
3. Optional: set `MUSIC_1_SHUFFLE_START=true` for random seek. (E.g. for large single audio files containing multiple tracks.)
4. Confirm the key appears under `services.bot.environment` in `docker-compose.yml`.
5. Recreate the bot container.

The bundled compose file forwards slots 1–3. Copy the pattern for slots 4–25.

Folder names come only from these environment variables. Dropping files into a folder does not create a slash command until you set `MUSIC_FOLDER_n`.

### Gaming covers

Up to 25 game folders with audio are supported. Optional cover art: `cover.png` or `cover.jpg` next to tracks, or one shared `cover.*` under `gaming/`.

## HTTP from bot to Lavalink

Lavalink fetches local tracks over HTTP. The bot embeds `MUSIC_LOCAL_HTTP_HOST` in those URLs. aiohttp listens on `MUSIC_LOCAL_HTTP_BIND_HOST`.


| Context        | Typical values                                                    |
| -------------- | ----------------------------------------------------------------- |
| Docker Compose | `MUSIC_LOCAL_HTTP_HOST=bot`, `MUSIC_LOCAL_HTTP_BIND_HOST=0.0.0.0` |
| Host Python    | `MUSIC_LOCAL_HTTP_HOST=127.0.0.1`                                 |


Default port: `8765`. Keep `sources.http: true` in `application.yml`.

## YouTube OAuth

YouTube playback uses the youtube-plugin in `application.yml`.

1. Set `YOUTUBE_OAUTH_ENABLED=true` in `.env`.
2. Restart Lavalink.
3. Complete the device flow from Lavalink logs.
4. Store the refresh token in `YOUTUBE_OAUTH_REFRESH_TOKEN`.

Use a burner Google account. If signature errors continue, keep `plugins.youtube.remoteCipher` from the example file.

## Slash commands


| Command               | Role                                           |
| --------------------- | ---------------------------------------------- |
| `/music play <query>` | Search or stream via Lavalink                  |
| `/music stop`         | Disconnect and clear the session               |
| `/gaming`             | Play from `local_audio/music/gaming/<game>/`   |
| `/<folder>`           | Play from a registered `MUSIC_FOLDER_n` folder |


Join a voice channel before you play.

## Bare-metal Lavalink

This section applies only to host Python. See [BARE_METAL.md](BARE_METAL.md).

1. Copy `application.yml.example` to `application.yml`.
2. Download the official Lavalink server JAR.
3. Place it as `lavalink/Lavalink.jar`.
4. Set `LAVALINK_URI=http://127.0.0.1:2333`.
5. Match `LAVALINK_PASSWORD` to the YAML password.
6. Run `./run-local.sh` from the `lavalink` directory.

Prefer Java 21 LTS.

```bash
export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
./run-local.sh
```

Tracked files: `application.yml.example`, `run-local.sh`. Ignored files: `*.jar`, `application.yml`, `logs/`, `plugins/`.

## Troubleshooting


| Signal                                   | Likely cause                                                                |
| ---------------------------------------- | --------------------------------------------------------------------------- |
| `lavalink_http_probe_failed`             | Wrong `LAVALINK_URI`, network, or bind address                              |
| `lavalink_http_probe_ok` but no playback | Password mismatch or plugin failure                                         |
| `Authentication failed`                  | `LAVALINK_PASSWORD` does not match YAML                                     |
| `This video requires login`              | Enable YouTube OAuth                                                        |
| `Must find sig function`                 | Enable or fix `remoteCipher`                                                |
| `Authorization missing for … on GET /`   | Healthcheck or HTTP probe without auth. Often harmless if Wavelink connects |


Trigger `/music play` once. Then search `discord_bot.log` for `lavalink_http_probe_`. A lot of the time, OAuth is the issue :)