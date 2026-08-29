"""
Serpent API (apiserpent.com) image search for tier list option images.
Results are normalized to the same row shape as Brave for shared download/preview helpers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple, cast

import aiohttp

from main_bot.server_configs.config import SERPENT_API_KEY, SERPENT_IMAGE_ENGINE

logger = logging.getLogger(__name__)

SERPENT_IMAGE_SEARCH_URL = "https://apiserpent.com/api/images"

_serpent_image_search_lock = asyncio.Lock()
_serpent_image_search_last_end: float = 0.0


class SerpentImageError(Exception):
    pass


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def _serpent_image_search_min_interval_s() -> float:
    return _env_float("SERPENT_IMAGE_SEARCH_MIN_INTERVAL", 1.05)


def serpent_image_to_row(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Serpent ``results.images[]`` entry to the Brave-compatible row dict."""
    original = item.get("original")
    thumb = item.get("thumbnail")
    if not isinstance(original, str) or not original.startswith("http"):
        original = thumb if isinstance(thumb, str) else None
    if not isinstance(thumb, str) or not thumb.startswith("http"):
        thumb = original if isinstance(original, str) else None
    page_url = item.get("pageUrl")
    return {
        "url": page_url if isinstance(page_url, str) else None,
        "title": item.get("title") if isinstance(item.get("title"), str) else None,
        "source": item.get("source") if isinstance(item.get("source"), str) else None,
        "properties": {
            "url": original,
            "placeholder": thumb,
        },
        "thumbnail": {"src": thumb} if thumb else None,
    }


async def _serpent_image_search_json(
    session: aiohttp.ClientSession,
    *,
    headers: Dict[str, str],
    params: Dict[str, str],
    timeout_s: int,
) -> Dict[str, Any]:
    global _serpent_image_search_last_end
    async with _serpent_image_search_lock:
        now = time.monotonic()
        if _serpent_image_search_last_end:
            wait = _serpent_image_search_min_interval_s() - (now - _serpent_image_search_last_end)
            if wait > 0:
                await asyncio.sleep(wait)
        try:
            async with session.get(
                SERPENT_IMAGE_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise SerpentImageError(f"Serpent images search failed ({resp.status}): {text[:500]}")
                raw = await resp.json()
        finally:
            _serpent_image_search_last_end = time.monotonic()
    if not isinstance(raw, dict):
        raise SerpentImageError("Serpent images search returned non-object JSON")
    return cast(Dict[str, Any], raw)


def _extract_serpent_images(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = payload.get("results")
    if isinstance(results, dict):
        images = results.get("images")
        if isinstance(images, list):
            return [x for x in images if isinstance(x, dict)]
    if isinstance(results, list):
        return [x for x in results if isinstance(x, dict)]
    return []


async def fetch_serpent_image_result_rows(
    session: aiohttp.ClientSession,
    search_query: str,
    *,
    count: int = 25,
    offset: int = 0,
    timeout_s: int = 45,
    min_source_width: Optional[int] = None,
    min_source_height: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    One Serpent image search request. Serpent has no offset API; ``offset`` is used as
    ``num`` (total images to request). ``next_api_offset`` is ``num`` when more may exist
  (capped at 100), else equal to ``offset`` to signal end.
    """
    del min_source_width, min_source_height  # decode-time check only for Serpent
    if not SERPENT_API_KEY:
        logger.warning("SERPENT_API_KEY is empty; skipping image search.")
        return [], 0

    query = (search_query or "").strip() or "photo"
    if offset > 0:
        num = min(100, max(count, offset + count))
    else:
        num = max(1, min(100, count))

    headers = {
        "X-API-Key": SERPENT_API_KEY,
        "Accept": "application/json",
    }
    engine = (SERPENT_IMAGE_ENGINE or "google").strip().lower() or "google"
    params: Dict[str, str] = {
        "q": query,
        "num": str(num),
        "engine": engine,
        "format": "simple",
        "size": "large",
    }

    try:
        payload = await _serpent_image_search_json(
            session, headers=headers, params=params, timeout_s=timeout_s
        )
    except asyncio.TimeoutError as e:
        raise SerpentImageError("Serpent images search timed out") from e
    except aiohttp.ClientError as e:
        raise SerpentImageError(f"Serpent images search request failed: {e}") from e

    if payload.get("success") is False and payload.get("error"):
        raise SerpentImageError(str(payload.get("error")))

    raw_items = _extract_serpent_images(payload)
    all_rows = [serpent_image_to_row(item) for item in raw_items]
    if offset > 0:
        rows = all_rows[offset:] if offset < len(all_rows) else []
    else:
        rows = all_rows
    next_num = num if num < 100 and len(raw_items) >= num else num
    return rows, next_num
