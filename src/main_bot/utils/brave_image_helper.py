import asyncio
import io
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, cast

import aiohttp
from PIL import Image

from main_bot.server_configs.config import BRAVE_SEARCH_API_KEY

logger = logging.getLogger(__name__)

BRAVE_IMAGE_SEARCH_URL = "https://api.search.brave.com/res/v1/images/search"

# Image Search query params only allow ``off`` or ``strict`` (``moderate`` returns HTTP 422).
BRAVE_IMAGE_SAFESEARCH = "strict"

_brave_image_search_lock = asyncio.Lock()
_brave_image_search_last_end: float = 0.0


def _brave_image_search_min_interval_s() -> float:
    """Free tier is often 1 req/s; override with BRAVE_IMAGE_SEARCH_MIN_INTERVAL (seconds)."""
    return float(os.environ.get("BRAVE_IMAGE_SEARCH_MIN_INTERVAL", "1.05"))


class BraveImageError(Exception):
    pass


async def _brave_image_search_json(
    session: aiohttp.ClientSession,
    *,
    headers: Dict[str, str],
    params: Dict[str, str],
    timeout_s: int,
) -> Dict[str, Any]:
    """
    One Brave image-search request, serialized and spaced for API rate limits.
    """
    global _brave_image_search_last_end
    async with _brave_image_search_lock:
        now = time.monotonic()
        if _brave_image_search_last_end:
            wait = _brave_image_search_min_interval_s() - (now - _brave_image_search_last_end)
            if wait > 0:
                await asyncio.sleep(wait)
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
                raw = await resp.json()
        finally:
            _brave_image_search_last_end = time.monotonic()
    if not isinstance(raw, dict):
        raise BraveImageError("Brave images search returned non-object JSON")
    return cast(Dict[str, Any], raw)


async def brave_image_search_query(
    session: aiohttp.ClientSession,
    query: str,
    *,
    count: int = 10,
    timeout_s: int = 30,
) -> Dict[str, Any]:
    """
    Public helper for one raw image search (throttled, same path as the bot). For ad-hoc
    scripts, using this keeps JSON dumps and option downloads from double-hitting rate limits
    with an unthrottled call.
    """
    if not BRAVE_SEARCH_API_KEY:
        raise BraveImageError("BRAVE_SEARCH_API_KEY is empty")
    headers: Dict[str, str] = {
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        "Accept": "application/json",
    }
    params: Dict[str, str] = {
        "q": query.strip(),
        "count": str(max(1, min(20, count))),
        "safesearch": BRAVE_IMAGE_SAFESEARCH,
    }
    return await _brave_image_search_json(session, headers=headers, params=params, timeout_s=timeout_s)


# Many CDNs require a normal browser user-agent; Brave CDNs work with a real browser-like client.
_DEFAULT_IMAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


@dataclass(frozen=True)
class BraveImageResult:
    """``url`` is a direct image URL suitable for download (not the Brave result page)."""

    url: str
    thumbnail_url: Optional[str] = None
    page_url: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None


def tierlist_image_min_size_px() -> Tuple[int, int]:
    """
    Minimum width/height (pixels) for tier list preview and saved option images.
    When Brave omits size metadata, the image is still tried and this is enforced at decode time.

    Override with ``BRAVE_TIERLIST_IMAGE_MIN_WIDTH`` and ``BRAVE_TIERLIST_IMAGE_MIN_HEIGHT`` (default 400 each).
    Unset or blank values use the default (empty vars in ``.env`` are common).
    """
    default = 400

    def _from_env(key: str) -> int:
        raw = os.environ.get(key)
        if raw is None or not str(raw).strip():
            return default
        return _as_positive_int(raw.strip()) or default

    return (_from_env("BRAVE_TIERLIST_IMAGE_MIN_WIDTH"), _from_env("BRAVE_TIERLIST_IMAGE_MIN_HEIGHT"))


def _as_positive_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    return n


def _brave_result_source_dims(result: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Original image size from ``properties`` when the API provides it."""
    props = result.get("properties")
    if not isinstance(props, dict):
        return None
    w = _as_positive_int(props.get("width"))
    h = _as_positive_int(props.get("height"))
    if w is not None and h is not None:
        return (w, h)
    return None


def _brave_result_meets_min_source_metadata(
    result: Dict[str, Any], min_w: int, min_h: int
) -> bool:
    """If dimensions are present, they must be large enough; missing dimensions are allowed through."""
    d = _brave_result_source_dims(result)
    if d is None:
        return True
    return d[0] >= min_w and d[1] >= min_h


def tierlist_option_image_search_query(
    option_text: str,
    *,
    image_search_prefix: Optional[str] = None,
) -> str:
    """
    Builds a Brave Image ``q=`` for a tier list option: optional ``image_search_prefix`` plus
    the option name only. The list title and the word ``image`` are omitted (the prefix field
    carries context; Brave image search is already image-oriented).
    """
    o = (option_text or "").strip()
    p = (image_search_prefix or "").strip()
    if p and o:
        return f"{p} {o}"
    if o:
        return o
    if p:
        return p
    return ""


def _candidate_image_urls(result: Dict[str, Any]) -> List[str]:
    """
    Download order: **source full-size** (``properties.url``) first, then the larger
    ``properties.placeholder`` when present. Brave's tiny result **thumbnail** is only used
    when nothing else is available — it is too small for preview quality.
    """
    out: List[str] = []
    seen: set[str] = set()

    def add(u: Optional[str]) -> None:
        if u and u.startswith("http") and u not in seen:
            seen.add(u)
            out.append(u)

    props = result.get("properties")
    if isinstance(props, dict):
        add(props.get("url"))
        add(props.get("placeholder"))

    thumb = result.get("thumbnail")
    if isinstance(thumb, dict):
        add(thumb.get("src") or thumb.get("url"))
    elif isinstance(thumb, str) and thumb.startswith("http"):
        add(thumb)

    return out


async def fetch_image_for_term(
    session: aiohttp.ClientSession,
    title_prefix: str,
    option: str,
    *,
    safesearch: str = BRAVE_IMAGE_SAFESEARCH,
    count: int = 1,
    timeout_s: int = 15,
) -> Optional[BraveImageResult]:
    """
    Searches Brave Images API for `f"{title_prefix} {option}"` and returns the first image result
    (single best-effort URL). Prefer :func:`search_and_save_brave_option_image` for downloads.
    """
    if not BRAVE_SEARCH_API_KEY:
        logger.warning("BRAVE_SEARCH_API_KEY is empty; skipping image search.")
        return None

    query = f"{title_prefix} {option}".strip()
    headers = {
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        "Accept": "application/json",
    }
    params: Dict[str, str] = {
        "q": query,
        "count": str(max(1, count)),
        "safesearch": safesearch,
    }

    try:
        payload = await _brave_image_search_json(session, headers=headers, params=params, timeout_s=timeout_s)
    except asyncio.TimeoutError as e:
        raise BraveImageError("Brave images search timed out") from e
    except aiohttp.ClientError as e:
        raise BraveImageError(f"Brave images search request failed: {e}") from e

    results: List[Dict[str, Any]] = payload.get("results") or []
    if not results:
        logger.debug("Brave image search: empty results; query=%r snippet=%r", query, str(payload)[:500])
        return None

    first = results[0] or {}
    page_url = first.get("url")
    urls = _candidate_image_urls(first)
    if not urls:
        logger.debug(
            "Brave image search: no usable image URL; query=%r keys=%r",
            query,
            list(first.keys()),
        )
        return None

    return BraveImageResult(
        url=urls[0],
        thumbnail_url=None,
        page_url=page_url if isinstance(page_url, str) else None,
        title=first.get("title") if isinstance(first.get("title"), str) else None,
        source=first.get("source") if isinstance(first.get("source"), str) else None,
    )


async def download_and_save_image(
    session: aiohttp.ClientSession,
    url: str,
    *,
    output_path: str,
    referer: Optional[str] = None,
    timeout_s: int = 20,
    max_bytes: int = 6_000_000,
    min_size: tuple[int, int] = (32, 32),
) -> str:
    """
    Downloads an image URL, converts to RGB JPEG for consistency, and saves to output_path.
    Returns the output_path.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    headers = dict(_DEFAULT_IMAGE_HEADERS)
    if referer:
        headers["Referer"] = referer

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
            headers=headers,
        ) as resp:
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
        w, h = img.size
        if w < min_size[0] or h < min_size[1]:
            raise BraveImageError(f"Image too small ({w}x{h})")
        img.save(output_path, format="JPEG", quality=85, optimize=True)
        return output_path
    except BraveImageError:
        raise
    except Exception as e:
        raise BraveImageError(f"Failed to decode/save image: {e}") from e


async def fetch_brave_image_result_rows(
    session: aiohttp.ClientSession,
    search_query: str,
    *,
    count: int = 20,
    offset: int = 0,
    timeout_s: int = 25,
    min_source_width: Optional[int] = None,
    min_source_height: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    One Brave image search page: returns ``(results, next_api_offset)``.

    ``results`` are filtered when ``min_source_width`` and ``min_source_height`` are both set:
    if Brave reports ``properties.width`` / ``properties.height`` and either side is below the
    minimum, that result is dropped. Rows with missing size metadata are kept (decode-time check
    in :func:`try_save_image_from_brave_result_row` still applies).

    ``next_api_offset`` is the offset to pass for the *next* Brave request (``offset`` of this
    request plus the number of results returned in the response, not the number after filtering).
    """
    if not BRAVE_SEARCH_API_KEY:
        logger.warning("BRAVE_SEARCH_API_KEY is empty; skipping image search.")
        return [], 0

    query = (search_query or "").strip() or "photo"
    headers = {
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        "Accept": "application/json",
    }
    n = max(1, min(100, count))
    of = max(0, offset)
    params: Dict[str, str] = {
        "q": query,
        "count": str(n),
        "safesearch": BRAVE_IMAGE_SAFESEARCH,
        "offset": str(of),
    }

    payload = await _brave_image_search_json(
        session, headers=headers, params=params, timeout_s=timeout_s
    )

    raw: List[Dict[str, Any]] = []
    for r in payload.get("results") or []:
        if isinstance(r, dict):
            raw.append(r)
    do_meta = min_source_width is not None and min_source_height is not None
    mw = int(min_source_width) if do_meta else 0
    mh = int(min_source_height) if do_meta else 0

    out: List[Dict[str, Any]] = []
    for r in raw:
        if do_meta and not _brave_result_meets_min_source_metadata(r, mw, mh):
            continue
        out.append(r)

    next_offset = of + len(raw)
    return out, next_offset


async def try_save_image_from_brave_result_row(
    session: aiohttp.ClientSession,
    result: Dict[str, Any],
    *,
    output_path: str,
    min_size: Optional[Tuple[int, int]] = None,
) -> Optional[str]:
    """
    Download the first working candidate for a single Brave ``image_result`` object.
    Returns the image URL that was saved, or None.

    ``min_size`` defaults to :func:`tierlist_image_min_size_px` (decoded pixel floor after download).
    """
    mw, mh = min_size or tierlist_image_min_size_px()
    page_url: Optional[str] = result.get("url") if isinstance(result.get("url"), str) else None
    for image_url in _candidate_image_urls(result):
        try:
            await download_and_save_image(
                session,
                image_url,
                output_path=output_path,
                referer=page_url,
                min_size=(mw, mh),
            )
            return image_url
        except BraveImageError as e:
            logger.debug("try_save row failed for %r: %s", image_url[:100], e)
            continue
    return None


async def filter_brave_rows_to_previewable(
    session: aiohttp.ClientSession,
    rows: List[Dict[str, Any]],
    *,
    max_concurrent: int = 5,
    min_size: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    """
    Return only Brave result rows for which a real image can be downloaded and decoded,
    in the same order as ``rows``.

    This mirrors what the tier-list image picker needs so dead links / blocked URLs are
    not counted as navigable "hits".
    """
    if not rows:
        return []
    mw, mh = min_size or tierlist_image_min_size_px()
    ms: Tuple[int, int] = (mw, mh)
    sem = asyncio.Semaphore(max(1, min(12, int(max_concurrent))))
    order_kept: List[Optional[Dict[str, Any]]] = [None] * len(rows)

    async def run_one(i: int, row: Dict[str, Any]) -> None:
        async with sem:
            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
            try:
                os.close(fd)
                u = await try_save_image_from_brave_result_row(
                    session, row, output_path=tmp_path, min_size=ms
                )
                if u:
                    order_kept[i] = row
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    await asyncio.gather(*[run_one(i, r) for i, r in enumerate(rows)])
    return [r for r in order_kept if r is not None]


async def search_and_save_brave_option_image(
    session: aiohttp.ClientSession,
    title_prefix: str,
    option: str,
    *,
    output_path: str,
    result_count: int = 10,
    timeout_s: int = 20,
    search_query: Optional[str] = None,
    debug_dump_search_json_path: Optional[str] = None,
) -> Optional[str]:
    """
    Searches Brave Images, then tries each result's URLs in quality order (source URL, then
    placeholder, then thumbnail last) across several results until a decodable, non-trivial image
    is saved. Returns the image URL that worked, or None.

    If ``debug_dump_search_json_path`` is set, the image-search JSON response is written there
    (useful for dry-run scripts without a second API call).
    """
    if not BRAVE_SEARCH_API_KEY:
        logger.warning("BRAVE_SEARCH_API_KEY is empty; skipping image search.")
        return None

    if search_query is not None:
        query = (search_query or "").strip()
    else:
        query = f"{(title_prefix or '').strip()} {(option or '').strip()}".strip()
    if not query:
        query = (option or "").strip() or (title_prefix or "").strip() or "photo"
    mw, mh = tierlist_image_min_size_px()
    page_size = max(1, min(20, result_count))
    off = 0
    max_brave_offset = 120
    dump_written = False

    while off < max_brave_offset:
        try:
            results, next_off = await fetch_brave_image_result_rows(
                session,
                query,
                count=page_size,
                offset=off,
                timeout_s=timeout_s,
                min_source_width=mw,
                min_source_height=mh,
            )
        except asyncio.TimeoutError as e:
            raise BraveImageError("Brave images search timed out") from e
        except aiohttp.ClientError as e:
            raise BraveImageError(f"Brave images search request failed: {e}") from e

        if debug_dump_search_json_path and not dump_written:
            with open(debug_dump_search_json_path, "w", encoding="utf-8") as dfp:
                json.dump({"query": query, "results": results}, dfp, indent=2)
            dump_written = True

        for result in results:
            url = await try_save_image_from_brave_result_row(
                session, result, output_path=output_path, min_size=(mw, mh)
            )
            if url:
                return url

        if next_off <= off:
            break
        off = next_off

    logger.debug("Brave image search: no saveable image for query=%r", query)
    return None
