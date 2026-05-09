"""Loopback HTTP server so Lavalink can load local music via ``http://`` (HTTP source)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

from aiohttp import web


class LocalMusicHttpServer:
    """Serves flat audio folders over HTTP (e.g. ``local_audio/music/jazz``, mounted ``brainrot`` elsewhere)."""

    __slots__ = ("_runner", "allowed_folders", "folder_roots", "host", "local_music_root", "port")

    def __init__(
        self,
        local_music_root: Path,
        *,
        allowed_folders: frozenset[str],
        folder_roots: Optional[dict[str, Path]] = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.local_music_root = local_music_root.resolve()
        self.folder_roots = {k: v.resolve() for k, v in (folder_roots or {}).items()}
        self.allowed_folders = allowed_folders
        self.host = host
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
            name = request.match_info["name"]
            if folder not in self.allowed_folders:
                return web.Response(status=404)
            if "/" in name or "\\" in name or name in (".", ".."):
                return web.Response(status=400)
            root = self._physical_root(folder).resolve()
            try:
                if folder in self.folder_roots:
                    root.relative_to(self.folder_roots[folder])
                else:
                    root.relative_to(self.local_music_root)
            except ValueError:
                return web.Response(status=403)
            candidate = (root / name).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return web.Response(status=403)
            if not candidate.is_file():
                return web.Response(status=404)
            return web.FileResponse(candidate)

        app = web.Application()
        app.router.add_get("/{folder}/{name}", handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
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
        if len(rel.parts) != 1:
            raise ValueError("local music folder must be flat (no subdirectories)")
        seg = quote(rel.name, safe="")
        return f"http://{self.host}:{self.port}/{folder}/{seg}"
