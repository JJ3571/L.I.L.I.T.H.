"""Tests for ``main_bot.utils.local_track_artwork``."""

from __future__ import annotations

from pathlib import Path

from main_bot.utils.local_track_artwork import extract_embedded_cover


def test_extract_embedded_cover_non_audio_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "readme.txt"
    p.write_bytes(b"not music")
    assert extract_embedded_cover(p) is None
