"""Loopback HTTP server so Lavalink can load local music via ``http://`` (HTTP source)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from aiohttp import web


def _filepath_to_safe_parts(filepath: str) -> Optional[list[str]]:
    """Split URL path remainder into safe components (no traversal)."""
    raw = filepath.strip().strip("/")
    if not raw:
        return None
    parts: list[str] = []
    for segment in raw.split("/"):
        seg = unquote(segment)
        if seg in ("", ".", "..") or "/" in seg or "\\" in seg:
            return None
        parts.append(seg)
    return parts


class LocalMusicHttpServer:
    """Serves local audio under ``allowed_folders`` — flat dirs, except ``gaming`` allows nested paths.

    ``host`` is the hostname/IP embedded in Lavalink-facing URLs (``http://host:port/...``). ``bind_host`` is the
    address passed to aiohttp for listening; when omitted it matches ``host``. Use ``bind_host='0.0.0.0'`` plus
    ``host`` set to the Compose service hostname (e.g. ``bot``) when Lavalink reaches this server across Docker.
    """

    __slots__ = ("_runner", "allowed_folders", "folder_roots", "listen_host", "local_music_root", "port", "public_host")

    def __init__(
        self,
        local_music_root: Path,
        *,
        allowed_folders: frozenset[str],
        folder_roots: Optional[dict[str, Path]] = None,
        host: str = "127.0.0.1",
        bind_host: Optional[str] = None,
        port: int = 8765,
    ) -> None:
        self.local_music_root = local_music_root.resolve()
        self.folder_roots = {k: v.resolve() for k, v in (folder_roots or {}).items()}
        self.allowed_folders = allowed_folders
        self.public_host = host
        self.listen_host = bind_host if bind_host is not None else host
        self.port = port
        self._runner: web.AppRunner | None = None

    def _physical_root(self, folder: str) -> Path:
        if folder in self.folder_roots:
            return self.folder_roots[folder]
        return (self.local_music_root / folder).resolve()

    async def start(self) -> None:
        if self._runner is not None:
            return

        async def handler(request: web.Request) -> web.StreamResponse:
            folder = request.match_info["folder"]
            filepath_segment = request.match_info["filepath"]
            if folder not in self.allowed_folders:
                return web.Response(status=404)
            parts = _filepath_to_safe_parts(filepath_segment)
            if parts is None:
                return web.Response(status=400)
            if folder != "gaming" and len(parts) != 1:
                return web.Response(status=400)

            root = self._physical_root(folder).resolve()
            try:
                if folder in self.folder_roots:
                    root.relative_to(self.folder_roots[folder])
                else:
                    root.relative_to(self.local_music_root)
            except ValueError:
                return web.Response(status=403)

            candidate = root.joinpath(*parts).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return web.Response(status=403)
            if not candidate.is_file():
                return web.Response(status=404)
            return web.FileResponse(candidate)

        app = web.Application()
        app.router.add_get(r"/{folder}/{filepath:.+}", handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.listen_host, self.port)
        await site.start()
        self._runner = runner

    async def stop(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None

    def url_for_file(self, folder: str, path: Path) -> str:
        if folder not in self.allowed_folders:
            raise ValueError(f"folder {folder!r} is not served by this server")
        resolved = path.resolve()
        base = self._physical_root(folder).resolve()
        rel = resolved.relative_to(base)
        if folder != "gaming" and len(rel.parts) != 1:
            raise ValueError("local music folder must be flat (no subdirectories)")
        segs = [quote(part, safe="") for part in rel.parts]
        tail = "/".join(segs)
        return f"http://{self.public_host}:{self.port}/{folder}/{tail}"
