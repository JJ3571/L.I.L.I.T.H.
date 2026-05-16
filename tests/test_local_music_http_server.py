"""Tests for ``main_bot.utils.jazz_http_server.LocalMusicHttpServer``."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import ClientSession

from main_bot.utils.jazz_http_server import LocalMusicHttpServer, _filepath_to_safe_parts


def test_filepath_to_safe_parts() -> None:
    assert _filepath_to_safe_parts("a/b.mp3") == ["a", "b.mp3"]
    assert _filepath_to_safe_parts("/a/b.mp3") == ["a", "b.mp3"]
    assert _filepath_to_safe_parts("..") is None
    assert _filepath_to_safe_parts("a/../b") is None


@pytest.mark.asyncio
async def test_local_music_http_nested_gaming(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    gaming = music_root / "gaming" / "risk-of-rain"
    gaming.mkdir(parents=True)
    audio = gaming / "song.mp3"
    audio.write_bytes(b"fake")

    port = 28765
    srv = LocalMusicHttpServer(
        music_root,
        allowed_folders=frozenset({"gaming", "jazz"}),
        host="127.0.0.1",
        port=port,
    )
    await srv.start()
    try:
        url = srv.url_for_file("gaming", audio)
        assert url.endswith("/gaming/risk-of-rain/song.mp3")
        async with ClientSession() as session:
            async with session.get(url) as resp:
                assert resp.status == 200
                assert await resp.read() == b"fake"
            bad = f"http://127.0.0.1:{port}/gaming/foo/..%2F..%2Fetc/passwd"
            async with session.get(bad) as resp2:
                assert resp2.status == 400
    finally:
        await srv.stop()


@pytest.mark.asyncio
async def test_public_host_urls_while_listen_on_loopback(tmp_path: Path) -> None:
    """Lavalink URL host can differ from aiohttp bind (Docker: listen 0.0.0.0, URL hostname = service name)."""
    music_root = tmp_path / "music"
    jazz = music_root / "jazz"
    jazz.mkdir(parents=True)
    f = jazz / "a.mp3"
    f.write_bytes(b"z")
    port = 28767
    srv = LocalMusicHttpServer(
        music_root,
        allowed_folders=frozenset({"jazz"}),
        host="lavalink-bot",
        bind_host="127.0.0.1",
        port=port,
    )
    await srv.start()
    try:
        url = srv.url_for_file("jazz", f)
        assert url == f"http://lavalink-bot:{port}/jazz/a.mp3"
        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{port}/jazz/a.mp3") as resp:
                assert resp.status == 200
                assert await resp.read() == b"z"
    finally:
        await srv.stop()


@pytest.mark.asyncio
async def test_local_music_http_flat_non_gaming_rejects_nested(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    jazz = music_root / "jazz"
    jazz.mkdir(parents=True)
    f = jazz / "a.mp3"
    f.write_bytes(b"x")
    srv = LocalMusicHttpServer(music_root, allowed_folders=frozenset({"jazz"}), host="127.0.0.1", port=28766)
    await srv.start()
    try:
        with pytest.raises(ValueError, match="flat"):
            nested = jazz / "sub" / "b.mp3"
            nested.parent.mkdir()
            nested.write_bytes(b"y")
            srv.url_for_file("jazz", nested)
    finally:
        await srv.stop()
