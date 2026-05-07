"""Embedded album-art extraction for local audio files (gaming folder embeds)."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

MIME_TO_SUFFIX: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def _suffix_for_mime(mime: Optional[str]) -> str:
    if not mime:
        return "jpg"
    key = mime.decode("utf-8", errors="ignore") if isinstance(mime, bytes) else str(mime)
    key = key.lower().strip().split(";", 1)[0].strip()
    return MIME_TO_SUFFIX.get(key, "jpg")


def extract_embedded_cover(audio_path: Path) -> tuple[bytes, str] | None:
    """First embedded cover as ``(raw_bytes, file_suffix)`` for Discord ``filename=``. ``None`` if missing."""

    resolved = Path(audio_path).expanduser().resolve(strict=False)

    from mutagen import File as mf_open
    from mutagen.flac import FLAC
    from mutagen.flac import Picture as FlacPicture
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4

    mf = mf_open(str(resolved), easy=False)
    if mf is None:
        return None

    if isinstance(mf, FLAC) and mf.pictures:
        pic = mf.pictures[0]
        if pic.data and len(pic.data) >= 256:
            return pic.data, _suffix_for_mime(pic.mime)

    if isinstance(mf, MP3) and mf.tags is not None:
        for blob in mf.tags.getall("APIC"):
            data = getattr(blob, "data", None)
            if isinstance(data, (bytes, bytearray)) and len(data) >= 256:
                return bytes(data), _suffix_for_mime(getattr(blob, "mime", None))

    if isinstance(mf, MP4) and mf.tags:
        blobs = mf.tags.get("covr")
        if blobs:
            b0 = blobs[0]
            if isinstance(b0, (bytes, bytearray)) and len(b0) >= 256:
                bb = bytes(b0)
                suf = "png" if bb.startswith(b"\x89PNG\r\n\x1a\n") else "jpg"
                return bb, suf

    tags = getattr(mf, "tags", None)
    if tags is None:
        return None

    for key_raw in getattr(tags, "keys", lambda: ())():
        if str(key_raw).lower() != "metadata_block_picture":
            continue
        vals = tags.get(key_raw)
        if not vals:
            continue
        first = vals[0]

        blob: Optional[bytes] = None
        raw_v = getattr(first, "value", first)
        if isinstance(raw_v, bytes):
            blob = raw_v
        elif isinstance(raw_v, str):
            blob = base64.standard_bdecode(raw_v)

        if not blob:
            continue

        bio = io.BytesIO(blob)
        try:
            pic = FlacPicture(data=bio.read())
            if pic.data and len(pic.data) >= 256:
                return pic.data, _suffix_for_mime(pic.mime)
        except Exception:
            continue

    return None
