"""Paths anchored to the repository root (parent of ``src/``)."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Repository root directory."""
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = project_root()


def runtime_bot_log_path() -> Path:
    """On-disk path for the combined runtime log (Nextcord library + ``main_bot``).

    Honors ``BOT_LOG_FILE`` env; relative paths resolve under ``PROJECT_ROOT``.
    Default when unset: ``<project>/logs/bot-runtime.log`` (typically bind-mounted under Docker).
    """

    raw = os.environ.get("BOT_LOG_FILE", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return (p.resolve() if p.is_absolute() else (PROJECT_ROOT / p).resolve())
    return (PROJECT_ROOT / "logs" / "bot-runtime.log").resolve()


# Local audio asset roots (typically gitignored under ``/local_audio``).
LOCAL_AUDIO_ROOT = PROJECT_ROOT / "local_audio"

# Lavalink loopback: env-configured flat dirs and ``music/gaming/<subfolder>/`` under here.
LOCAL_MUSIC_ROOT = LOCAL_AUDIO_ROOT / "music"

# Brainrot sfx expected under ``LOCAL_AUDIO_ROOT / "brainrot"``: dodgeball.mp3, plankton.mp3, steel_pipe.mp3.
