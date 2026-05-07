"""Paths anchored to the repository root (parent of ``src/``)."""
from pathlib import Path


def project_root() -> Path:
    """Repository root directory."""
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = project_root()

# Local audio asset roots (typically gitignored under ``/local_audio``).
LOCAL_AUDIO_ROOT = PROJECT_ROOT / "local_audio"

# Lavalink loopback folder playback: flat dirs ``jazz``, ``lofi``, ``gaming``, … under here.
LOCAL_MUSIC_ROOT = LOCAL_AUDIO_ROOT / "music"

# Brainrot sfx expected under ``LOCAL_AUDIO_ROOT / "brainrot"``: dodgeball.mp3, plankton.mp3, steel_pipe.mp3.
