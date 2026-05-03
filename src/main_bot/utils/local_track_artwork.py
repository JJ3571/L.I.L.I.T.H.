"""Read embedded album art from local audio files (gaming folder, etc.)."""

from __future__ import annotations

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
    key = mime.lower().strip()
    return MIME_TO_SUFFIX.get(key, MIME_TO_SUFFIX.get(key.split(";")[0].strip(), "jpg"))


def extract_embedded_cover(audio_path: Path) -> tuple[bytes, str] | None:
    """Return ``(bytes, discord_filename_suffix_without_dot)`` for the first usable cover picture, else ``None``."""
    from mutagen import File as mutagen_open
    from mutagen.flac import FLAC
    from mutagen.id3 import APIC as APIC_FRAME
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    import mutagen.oggopus
    import mutagen.oggvorbis

    resolved = audio_path.expanduser().resolve(strict=False)

    mf = mutagen_open(resolved)
    if mf is None:
        return None

    # FLAC: Picture list
    if isinstance(mf, FLAC) and mf.pictures:
        pic = mf.pictures[0]
        if pic.data:
            suf = _suffix_for_mime(getattr(pic, "mime", None))
            return pic.data, suf

    # MPEG with ID3: APIC
    if isinstance(mf, MP3):
        mp3_tags = mf.tags or {}
        frames = getattr(mp3_tags, "getall", lambda _k: [])("APIC")  # pyright uses list
        for frame in frames if frames else mp3_tags.values():
            try:
                if isinstance(frame, APIC_FRAME):
                    payload = getattr(frame, "data", None) or getattr(frame, "value", None)
                    if isinstance(payload, bytes) and len(payload) >= 256:
                        mime = getattr(frame, "mime", None)
                        suf = _suffix_for_mime(mime.decode() if isinstance(mime, bytes) else mime)
                        return payload, suf
            except Exception:
                continue

    # MP4 / M4A
    if isinstance(mf, MP4) and mf.tags:
        covr = mf.tags.get("covr")
        if covr:
            entry = covr[0]
            data = getattr(entry, "data", entry) if not isinstance(entry, (bytes, bytearray)) else entry
            if isinstance(data, bytes) and len(data) >= 256:
                # MP4 cover is JPEG by default unless MP4Cover.FORMAT_PNG etc.
                return data, _suffix_for_mime("image/jpeg")

    # Ogg Opus / Vorbis (METADATA_BLOCK_PICTURE)
    for cls in (
        getattr(mutagen.oggopus, "Open", None),
        getattr(mutagen.oggvorbis, "Open", None),
    ):
        pass
    try:
        v = mf
        if hasattr(v.tags, "as_dict"):
            dic = v.tags.as_dict()
            pics_meta = dic.get("metadata_block_picture") or dic.get("METADATA_BLOCK_PICTURE")
            if pics_meta:
                blob = pics_meta[0].value if hasattr(pics_meta[0], "value") else pics_meta[0]
                raw = getattr(blob, "data", blob) if not isinstance(blob, (bytes, bytearray)) else blob
                if isinstance(raw, (bytes, bytearray)) and len(raw) >= 256:
                    # Ogg picture block: skip header describing type/mime/description
                    bio = io.BytesIO(bytes(raw))
                    try:
                        from mutagen.flac import Picture

                        bio.seek(0)
                        parsed = Picture(data=bio.read())
                        if parsed.data:
                            suf = _suffix_for_mime(getattr(parsed, "mime", None))
                            return parsed.data, suf
                    except Exception:
                        img = bytes(raw)
                        ofs = img.find(b"\xff\xd8\xff")
                        if ofs >= 0 and len(img) - ofs >= 512:
                            return img[ofs:], "jpg"
                        if img.startswith(b"\x89PNG"):
                            return img, "png"
    except Exception:
        pass

    return None
