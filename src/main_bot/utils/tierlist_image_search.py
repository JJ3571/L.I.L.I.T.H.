"""
Unified tier list image search: Serpent (Google Images) preferred, Brave fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from main_bot.server_configs.config import (
    BRAVE_SEARCH_API_KEY,
    SERPENT_API_KEY,
    TIERLIST_IMAGE_ENGINE,
)
from main_bot.utils.brave_image_helper import (
    BraveImageError,
    _candidate_image_urls,
    fetch_brave_image_result_rows,
    filter_brave_rows_to_previewable,
    tierlist_image_min_size_px,
    tierlist_option_image_search_query,
    try_save_image_from_brave_result_row,
)
from main_bot.utils.serpent_image_helper import (
    SerpentImageError,
    fetch_serpent_image_result_rows,
)

logger = logging.getLogger(__name__)

TierlistImageError = BraveImageError


def image_search_configured() -> bool:
    return bool(_active_provider())


def image_search_provider_name() -> str:
    p = _active_provider()
    if p == "serpent":
        return "Google (Serpent)"
    if p == "brave":
        return "Brave"
    return "none"


def _active_provider() -> str:
    pref = (TIERLIST_IMAGE_ENGINE or "").strip().lower()
    if pref == "serpent" and SERPENT_API_KEY:
        return "serpent"
    if pref == "brave" and BRAVE_SEARCH_API_KEY:
        return "brave"
    if SERPENT_API_KEY:
        return "serpent"
    if BRAVE_SEARCH_API_KEY:
        return "brave"
    return ""


async def fetch_image_result_rows(
    session: aiohttp.ClientSession,
    search_query: str,
    *,
    count: int = 25,
    offset: int = 0,
    timeout_s: int = 45,
    min_source_width: Optional[int] = None,
    min_source_height: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    provider = _active_provider()
    if provider == "serpent":
        return await fetch_serpent_image_result_rows(
            session,
            search_query,
            count=count,
            offset=offset,
            timeout_s=timeout_s,
            min_source_width=min_source_width,
            min_source_height=min_source_height,
        )
    if provider == "brave":
        return await fetch_brave_image_result_rows(
            session,
            search_query,
            count=count,
            offset=offset,
            timeout_s=min(timeout_s, 30),
            min_source_width=min_source_width,
            min_source_height=min_source_height,
        )
    return [], 0


async def filter_rows_to_previewable(
    session: aiohttp.ClientSession,
    rows: List[Dict[str, Any]],
    *,
    max_concurrent: int = 5,
    min_size: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    return await filter_brave_rows_to_previewable(
        session, rows, max_concurrent=max_concurrent, min_size=min_size
    )


def preview_url_from_row(row: Dict[str, Any]) -> Optional[str]:
    """Thumbnail or placeholder URL for fast embed preview (no download)."""
    urls = _candidate_image_urls(row)
    if not urls:
        return None
    props = row.get("properties")
    if isinstance(props, dict):
        ph = props.get("placeholder")
        if isinstance(ph, str) and ph.startswith("http"):
            return ph
    thumb = row.get("thumbnail")
    if isinstance(thumb, dict):
        t = thumb.get("src") or thumb.get("url")
        if isinstance(t, str) and t.startswith("http"):
            return t
    return urls[-1] if urls else None


async def try_save_image_from_result_row(
    session: aiohttp.ClientSession,
    result: Dict[str, Any],
    *,
    output_path: str,
    min_size: Optional[Tuple[int, int]] = None,
) -> Optional[str]:
    return await try_save_image_from_brave_result_row(
        session, result, output_path=output_path, min_size=min_size
    )


__all__ = [
    "TierlistImageError",
    "BraveImageError",
    "SerpentImageError",
    "fetch_image_result_rows",
    "filter_rows_to_previewable",
    "image_search_configured",
    "image_search_provider_name",
    "preview_url_from_row",
    "tierlist_image_min_size_px",
    "tierlist_option_image_search_query",
    "try_save_image_from_result_row",
]
