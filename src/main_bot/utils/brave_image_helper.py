import asyncio
import io
import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp
from PIL import Image

from main_bot.server_configs.config import BRAVE_SEARCH_API_KEY

logger = logging.getLogger(__name__)

BRAVE_IMAGE_SEARCH_URL = "https://api.search.brave.com/res/v1/images/search"


@dataclass(frozen=True)
class BraveImageResult:
    url: str
    thumbnail_url: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None


class BraveImageError(Exception):
    pass


async def fetch_image_for_term(
    session: aiohttp.ClientSession,
    title_prefix: str,
    option: str,
    *,
    safesearch: str = "moderate",
    count: int = 1,
    timeout_s: int = 15,
) -> Optional[BraveImageResult]:
    """
    Searches Brave Images API for `f"{title_prefix} {option}"` and returns the first image result.
    """
    if not BRAVE_SEARCH_API_KEY:
        logger.warning("BRAVE_SEARCH_API_KEY is empty; skipping image search.")
        return None

    query = f"{title_prefix} {option}".strip()
    headers = {
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        "Accept": "application/json",
    }
    params = {
        "q": query,
        "count": str(count),
        "safesearch": safesearch,
    }

    try:
        async with session.get(
            BRAVE_IMAGE_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise BraveImageError(f"Brave images search failed ({resp.status}): {text[:500]}")
            payload = await resp.json()
    except asyncio.TimeoutError as e:
        raise BraveImageError("Brave images search timed out") from e
    except aiohttp.ClientError as e:
        raise BraveImageError(f"Brave images search request failed: {e}") from e

    results = payload.get("results") or []
    if not results:
        return None

    first = results[0] or {}
    url = first.get("url")
    if not url:
        return None

    thumb = None
    thumbnail = first.get("thumbnail") or {}
    if isinstance(thumbnail, dict):
        thumb = thumbnail.get("src") or thumbnail.get("url")

    return BraveImageResult(
        url=url,
        thumbnail_url=thumb,
        title=first.get("title"),
        source=first.get("source"),
    )


async def download_and_save_image(
    session: aiohttp.ClientSession,
    url: str,
    *,
    output_path: str,
    timeout_s: int = 20,
    max_bytes: int = 6_000_000,
) -> str:
    """
    Downloads an image URL, converts to RGB JPEG for consistency, and saves to output_path.
    Returns the output_path.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
            if resp.status != 200:
                raise BraveImageError(f"Image download failed ({resp.status})")

            data = await resp.content.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise BraveImageError("Image too large to download safely")
    except asyncio.TimeoutError as e:
        raise BraveImageError("Image download timed out") from e
    except aiohttp.ClientError as e:
        raise BraveImageError(f"Image download request failed: {e}") from e

    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.save(output_path, format="JPEG", quality=85, optimize=True)
        return output_path
    except Exception as e:
        raise BraveImageError(f"Failed to decode/save image: {e}") from e



