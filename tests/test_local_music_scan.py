"""Tests for ``main_bot.utils.local_music_scan``."""
from pathlib import Path

from main_bot.utils.local_music_scan import AUDIO_SUFFIXES, list_audio_files


def test_list_audio_files_empty_dir(tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    assert list_audio_files(d) == []


def test_list_audio_files_missing_dir(tmp_path: Path) -> None:
    assert list_audio_files(tmp_path / "nope") == []


def test_list_audio_files_filters_and_sorts(tmp_path: Path) -> None:
    d = tmp_path / "jazz"
    d.mkdir()
    (d / "b.mp3").write_bytes(b"x")
    (d / "a.flac").write_bytes(b"x")
    (d / "skip.txt").write_text("no")
    sub = d / "nested"
    sub.mkdir()
    (sub / "inside.mp3").write_bytes(b"x")

    got = list_audio_files(d)
    assert len(got) == 2
    assert got[0].name.lower() == "a.flac"
    assert got[1].name.lower() == "b.mp3"


def test_audio_suffixes_cover_common_types() -> None:
    assert ".mp3" in AUDIO_SUFFIXES
    assert ".wav" in AUDIO_SUFFIXES
    assert ".txt" not in AUDIO_SUFFIXES
