"""OpenCode Go chat completions client (OpenAI-compatible)."""

from __future__ import annotations

import logging
from typing import Any, Optional

import aiohttp
import requests

from main_bot.server_configs.config import (
    BRAVE_SEARCH_API_KEY,
    OPENCODE_API_KEY,
    OPENCODE_MODEL,
)

logger = logging.getLogger(__name__)

OPENCODE_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_OPENCODE_MODEL = "deepseek-v4-flash"
BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class OpenCodeError(Exception):
    """Raised when OpenCode Go is misconfigured or returns an error."""


def opencode_model() -> str:
    return OPENCODE_MODEL or DEFAULT_OPENCODE_MODEL


def _headers() -> dict[str, str]:
    if not OPENCODE_API_KEY:
        raise OpenCodeError("OPENCODE_API_KEY is not configured")
    return {
        "Authorization": f"Bearer {OPENCODE_API_KEY}",
        "Content-Type": "application/json",
    }


def _build_messages(user_prompt: str, system_prompt: Optional[str] = None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _build_payload(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    *,
    response_format: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": opencode_model(),
        "messages": _build_messages(user_prompt, system_prompt),
    }
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _extract_content(data: dict[str, Any]) -> Optional[str]:
    choices = data.get("choices")
    if not choices:
        return None
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None:
        return None
    return str(content).strip() or None


def chat_completion(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    *,
    response_format: Optional[str] = None,
    timeout_s: float = 120.0,
) -> Optional[str]:
    """Synchronous OpenCode Go chat completion."""
    payload = _build_payload(user_prompt, system_prompt, response_format=response_format)
    response = requests.post(
        f"{OPENCODE_BASE_URL}/chat/completions",
        headers=_headers(),
        json=payload,
        timeout=timeout_s,
    )
    if not response.ok:
        raise OpenCodeError(f"OpenCode API error {response.status_code}: {response.text[:500]}")
    return _extract_content(response.json())


async def async_chat_completion(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    *,
    response_format: Optional[str] = None,
    timeout_s: float = 120.0,
) -> Optional[str]:
    """Async OpenCode Go chat completion."""
    payload = _build_payload(user_prompt, system_prompt, response_format=response_format)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{OPENCODE_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        ) as response:
            body = await response.text()
            if response.status != 200:
                raise OpenCodeError(f"OpenCode API error {response.status}: {body[:500]}")
            return _extract_content(await response.json())


def brave_web_search(query: str, *, count: int = 5) -> str:
    """Fetch Brave web search snippets to ground LLM responses."""
    if not BRAVE_SEARCH_API_KEY:
        return ""

    response = requests.get(
        BRAVE_WEB_SEARCH_URL,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        },
        params={"q": query, "count": count},
        timeout=30,
    )
    if not response.ok:
        logger.warning("Brave web search failed (%s): %s", response.status_code, response.text[:200])
        return ""

    results = response.json().get("web", {}).get("results") or []
    snippets: list[str] = []
    for result in results[:count]:
        title = result.get("title", "Untitled")
        description = result.get("description", "")
        url = result.get("url", "")
        snippets.append(f"- {title}: {description} ({url})".strip())
    return "\n".join(snippets)
