Local Lavalink (development)

Files tracked in git:
  application.yml.example  — template; safe to commit
  run-local.sh             — helper launcher

Ignored by git (see repo root .gitignore):
  *.jar                    — Lavalink binary from lavalink.dev / GitHub releases
  application.yml          — your local copy (copy from example)
  logs/, plugins/          — runtime dirs Lavalink creates

Quick start:
  cd lavalink
  cp application.yml.example application.yml
  # Put the official Lavalink *Server* JAR from https://github.com/lavalink-devs/Lavalink/releases here.

Jar sanity check:
  The runnable Lavalink server is typically named Lavalink.jar in releases (standalone JVM server).
  A jar named "lavalink-client" might be a different artifact — verify it boots Lavalink before trusting search/play.

Note on jar names:
  Only jars matching Lavalink*.jar or exactly one *.jar are picked automatically.
  Prefer renaming the release artifact to Lavalink.jar if you ever need multiple jars in one folder.

Bot alignment:
  LAVALINK_URI=http://127.0.0.1:2333
  LAVALINK_PASSWORD must match lavalink.server.password in application.yml
  Docker Compose: mount ``application.yml`` at ``/opt/Lavalink/application.yml`` (official image path); wrong paths load
    defaults so HTTP may not listen on 2333 (``lavalink_http_probe_failed``). The bundled compose points the BOT at
    ``http://lavalink:2333`` — do not inject localhost LAVALINK_URI into the bot env there.
  If Wavelink never shows a CONNECTED node: verify ``lavalink/application.yml`` has ``address: …`` on its own line;
    merging ``address`` and ``http2`` onto one physical line breaks Spring YAML and Lavalink won't listen correctly.
  /music play uses YouTube search via the youtube-plugin declared in application.yml.example
  Env ``MUSIC_FOLDER_*`` registers flat ``local_audio/music/{name}`` as /name; /gaming serves nested ``local_audio/music/gaming/<game>/…`` over loopback HTTP (e.g. ``http://127.0.0.1:8765/gaming/<game>/filename``); other folders are single-segment paths.   Lavalink needs sources.http: true

Docker / VPS — which container is wrong?

  • File logs (Docker Compose): the bot writes ``discord_bot.log`` under host ``./logs/``; the same ``./logs`` directory
    is bind-mounted to Lavalink's ``/opt/Lavalink/logs`` (``application.yml`` → ``logging.file.name`` → ``lavalink.log``), so
    JVM/logback output sits beside the bot file—no second folder. Running the Lavalink JAR locally (``run-local.sh``)
    still uses ``lavalink/logs/lavalink.log`` next to the jar. Without the Lavalink mount, use ``docker compose logs -f lavalink``.

  • The example ``application.yml`` uses Spring placeholders: ``password: ${LAVALINK_PASSWORD}``, OAuth
    ``enabled: "${YOUTUBE_OAUTH_ENABLED:false}"``, ``refreshToken: "${YOUTUBE_OAUTH_REFRESH_TOKEN:}"``. Compose passes those
    from the host ``.env`` / Doppler into the **lavalink** service. You can also use Lavalink’s native env names
    (``PLUGINS_YOUTUBE_OAUTH_*``) which override YAML per Lavalink docs.

  • YouTube ``/music play`` still failing after OAuth? Add ``plugins.youtube.remoteCipher`` in ``application.yml`` (see
    ``application.yml.example``). OAuth fixes visitor/login for TV; ``Must find sig function`` needs remote cipher.

  • ``Authorization missing for … on GET /`` in Lavalink logs is usually the Docker healthcheck or the bot’s unauthenticated
    HTTP probe to ``/`` — not a failed Wavelink session. If you see ``Connection successfully established from Wavelink``,
    Lavalink auth for playback is fine.

  • On each ``ensure_lavalink``, the bot runs an HTTP GET to ``LAVALINK_URI`` (logged as ``lavalink_http_probe_ok`` /
    ``lavalink_http_probe_failed`` under logger ``nextcord.music``). Same stack as Wavelink uses for REST.

      probe_ok → Lavalink HTTP port answers from the bot process → suspect websocket/auth (password typo vs YAML,
      Lavalink logs ``Authentication failed``, plugin crash after bind).

      probe_failed → networking/DNS/bind (wrong ``LAVALINK_URI``, containers not on same Docker network,
      ``server.address`` still loopback-only inside Lavalink).

  • Easiest signal: trigger ``/music play`` once, then grep ``discord_bot.log`` for ``lavalink_http_probe_``.

Java 21 LTS (recommended):
  run-local.sh uses ``$JAVA_HOME/bin/java`` when JAVA_HOME is set. On macOS with multiple JDKs installed:
    export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
    ./run-local.sh
  The startup line prints the JVM version so you can confirm it is not picking Java 22+ by mistake.

Java 22+ noise:
  If you see warnings about System::load / native access, you can run with e.g.
    JAVA_OPTS="-Xmx512M --enable-native-access=ALL-UNNAMED" ./run-local.sh
  (Harmless for normal dev; Lavalink/JBoss may silence these over time.)

Production:
  Use systemd separately from this repo; no jar committed — mirror password, bind address, and plugins there.
