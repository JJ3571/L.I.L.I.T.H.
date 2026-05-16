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
  Docker Compose: the bundled docker-compose.yml points the BOT container at ``http://lavalink:2333`` — do not inject
    localhost LAVALINK_URI into the compose bot service env (inside the bot, 127.0.0.1 is wrong); see compose comments.
  If Wavelink never shows a CONNECTED node: verify ``lavalink/application.yml`` has ``address: …`` on its own line;
    merging ``address`` and ``http2`` onto one physical line breaks Spring YAML and Lavalink won't listen correctly.
  /music play uses YouTube search via the youtube-plugin declared in application.yml.example
  Env ``MUSIC_FOLDER_*`` registers flat ``local_audio/music/{name}`` as /name; /gaming serves nested ``local_audio/music/gaming/<game>/…`` over loopback HTTP (e.g. ``http://127.0.0.1:8765/gaming/<game>/filename``); other folders are single-segment paths. Lavalink needs sources.http: true

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
