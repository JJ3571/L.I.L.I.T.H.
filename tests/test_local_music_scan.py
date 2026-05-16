"""Tests for ``main_bot.utils.local_music_scan``."""
from pathlib import Path

from main_bot.utils.local_music_scan import (
    AUDIO_SUFFIXES,
    GAMING_AUDIO_SUBFOLDER_LIMIT,
    collect_gaming_audio_paths,
    format_music_folder_button_label,
    gaming_track_subslug,
    list_audio_files,
    list_gaming_audio_subfolders,
)


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


def test_list_gaming_audio_subfolders_ignores_empty_and_sorts(tmp_path: Path) -> None:
    root = tmp_path / "gaming"
    root.mkdir()
    (root / "b-game").mkdir()
    (root / "b-game" / "x.mp3").write_bytes(b"x")
    (root / "a-game").mkdir()
    (root / "a-game" / "y.flac").write_bytes(b"y")
    (root / "empty").mkdir()
    assert list_gaming_audio_subfolders(root) == ["a-game", "b-game"]


def test_collect_gaming_audio_paths(tmp_path: Path) -> None:
    root = tmp_path / "gaming"
    (root / "one").mkdir(parents=True)
    (root / "one" / "a.mp3").write_bytes(b"a")
    (root / "two").mkdir(parents=True)
    (root / "two" / "b.mp3").write_bytes(b"b")
    got = collect_gaming_audio_paths(root)
    assert len(got) == 2


def test_gaming_track_subslug(tmp_path: Path) -> None:
    root = tmp_path / "gaming"
    p = root / "minecraft" / "c.mp3"
    assert gaming_track_subslug(p, root) == "minecraft"


def test_format_music_folder_button_label() -> None:
    assert format_music_folder_button_label("risk-of-rain") == "Risk Of Rain"
    assert GAMING_AUDIO_SUBFOLDER_LIMIT == 25
