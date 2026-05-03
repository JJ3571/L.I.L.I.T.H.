"""Unit tests for config parsing helpers (no Discord API)."""

import json

import pytest

from main_bot.server_configs import config as cfg


def test_strip_hash_comments_outside_strings() -> None:
    text = '{"a": 1, # comment\n "b": "hash # inside string"}'
    cleaned = cfg._strip_hash_comments_outside_strings(text)
    data = json.loads(cleaned)
    assert data["a"] == 1
    assert data["b"] == "hash # inside string"


def test_strip_hash_inline_after_number_keeps_bracket() -> None:
    """'# label' same line must not swallow the closing `]` (Doppler-friendly array)."""
    text = "[421980223391924231 #General]"
    cleaned = cfg._strip_hash_comments_outside_strings(text)
    assert json.loads(cleaned.strip()) == [421980223391924231]


def test_relax_json_syntax_trailing_commas() -> None:
    raw = '{"x": [1, 2, ], "y": 3,}'
    relaxed = cfg._relax_json_syntax(raw)
    data = json.loads(relaxed)
    assert data["x"] == [1, 2]
    assert data["y"] == 3


def test_get_json_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_JSON_KEY", '{"k": [1, 2]}')
    assert cfg._get_json("TEST_JSON_KEY", {}) == {"k": [1, 2]}


def test_get_json_int_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT_LIST", "[1, 2, 3]")
    assert cfg._get_json_int_list("TEST_INT_LIST") == [1, 2, 3]
