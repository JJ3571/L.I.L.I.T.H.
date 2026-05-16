"""Scan local audio folders (e.g. ``local_audio/music/jazz`` at repo root)."""
from __future__ import annotations

import re
from pathlib import Path

AUDIO_SUFFIXES = frozenset({".mp3", ".m4a", ".ogg", ".flac", ".wav", ".opus"})

# Max immediate subfolders under ``music/gaming`` for ``/gaming`` slash (Discord button row limit).
GAMING_AUDIO_SUBFOLDER_LIMIT = 25


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


def list_gaming_audio_subfolders(gaming_root: Path) -> list[str]:
    """Child directories of ``gaming_root`` that contain at least one audio file, sorted by name."""
    if not gaming_root.is_dir():
        return []
    names: list[str] = []
    for p in gaming_root.iterdir():
        if p.is_dir() and list_audio_files(p):
            names.append(p.name)
    names.sort(key=lambda s: s.lower())
    return names


def collect_gaming_audio_paths(gaming_root: Path) -> list[Path]:
    """All audio paths under immediate game subfolders of ``gaming_root`` (one level deep per game)."""
    paths: list[Path] = []
    for name in list_gaming_audio_subfolders(gaming_root):
        paths.extend(list_audio_files(gaming_root / name))
    return paths


def gaming_track_subslug(audio_path: Path, gaming_root: Path) -> str:
    """First path segment under ``gaming_root`` for a track (directory name on disk)."""
    try:
        rel = audio_path.resolve().relative_to(gaming_root.resolve())
    except ValueError:
        return ""
    return rel.parts[0] if rel.parts else ""


_SLUG_LABEL_RE = re.compile(r"[-_]+")


def format_music_folder_button_label(slug: str) -> str:
    """``risk-of-rain`` -> ``Risk Of Rain`` for button labels."""
    slug = slug.strip("-_")
    if not slug:
        return slug
    words = [w for w in _SLUG_LABEL_RE.split(slug) if w]
    if not words:
        return slug
    return " ".join(w.capitalize() for w in words)
