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
  /music play uses YouTube search via the youtube-plugin declared in application.yml.example
  /jazz, /lofi, /minecraft serve ``local_music/{folder}`` over loopback HTTP (URLs ``http://127.0.0.1:8765/{folder}/filename``); Lavalink needs sources.http: true

Java 22+ noise:
  If you see warnings about System::load / native access, you can run with e.g.
    JAVA_OPTS="-Xmx512M --enable-native-access=ALL-UNNAMED" ./run-local.sh
  (Harmless for normal dev; Lavalink/JBoss may silence these over time.)

Production:
  Use systemd separately from this repo; no jar committed — mirror password, bind address, and plugins there.
