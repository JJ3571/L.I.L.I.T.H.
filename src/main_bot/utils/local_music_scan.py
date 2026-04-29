"""Scan local audio folders (e.g. ``local_music/jazz`` at repo root)."""
from __future__ import annotations

from pathlib import Path

AUDIO_SUFFIXES = frozenset({".mp3", ".m4a", ".ogg", ".flac", ".wav", ".opus"})


def list_audio_files(directory: Path) -> list[Path]:
    """Return sorted absolute paths to audio files directly under ``directory`` (non-recursive)."""
    if not directory.is_dir():
        return []
    out: list[Path] = []
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES:
            out.append(p.resolve())
    out.sort(key=lambda x: x.name.lower())
    return out
