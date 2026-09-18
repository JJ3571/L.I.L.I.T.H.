"""Unit tests for OpenCode Go request headers (no live API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from main_bot.utils import opencode_client as oc


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(oc, "OPENCODE_API_KEY", "test-key")
    return "test-key"


def test_headers_include_session_and_user_agent(api_key: str) -> None:
    headers = oc._headers("conv-123")
    assert headers["Authorization"] == f"Bearer {api_key}"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == oc.OPENCODE_USER_AGENT
    assert headers["x-opencode-session"] == "conv-123"


def test_headers_generate_unique_session_when_omitted(api_key: str) -> None:
    first = oc._headers()
    second = oc._headers()
    assert first["x-opencode-session"]
    assert second["x-opencode-session"]
    assert first["x-opencode-session"] != second["x-opencode-session"]


def test_headers_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "OPENCODE_API_KEY", "")
    with pytest.raises(oc.OpenCodeError, match="OPENCODE_API_KEY is not configured"):
        oc._headers()


def test_chat_completion_sends_session_header(api_key: str) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    with patch("main_bot.utils.opencode_client.requests.post", return_value=mock_resp) as post:
        result = oc.chat_completion("hello", session_id="sess-abc")
    assert result == "hi"
    headers = post.call_args.kwargs["headers"]
    assert headers["x-opencode-session"] == "sess-abc"
    assert headers["User-Agent"] == oc.OPENCODE_USER_AGENT


def test_chat_completion_generates_session_header(api_key: str) -> None:
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    with patch("main_bot.utils.opencode_client.requests.post", return_value=mock_resp) as post:
        oc.chat_completion("hello")
    headers = post.call_args.kwargs["headers"]
    assert headers["x-opencode-session"]


async def test_async_chat_completion_sends_session_header(api_key: str) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 200

        async def text(self) -> str:
            return '{"choices":[{"message":{"content":"async-hi"}}]}'

        async def json(self) -> dict:
            return {"choices": [{"message": {"content": "async-hi"}}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    with patch("main_bot.utils.opencode_client.aiohttp.ClientSession", _FakeSession):
        result = await oc.async_chat_completion("hello", session_id="sess-async")
    assert result == "async-hi"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-opencode-session"] == "sess-async"
    assert headers["User-Agent"] == oc.OPENCODE_USER_AGENT


def test_format_missing_session_error() -> None:
    err = oc.OpenCodeError(
        'OpenCode API error 400: {"type":"error","error":{"type":"MissingSessionID"}}'
    )
    msg = oc.format_opencode_user_error(err)
    assert "session header" in msg.lower()
