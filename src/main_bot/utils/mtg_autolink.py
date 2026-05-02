"""Pure helpers for MTG message autocard (token spans, greedy match, caps)."""

from __future__ import annotations

import re
from typing import AbstractSet, Any, Dict, List, Mapping, MutableSet

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9']+")


def tokenize(content: str) -> List[str]:
    return TOKEN_PATTERN.findall(content)


def normalize_phrase(phrase: str) -> str:
    return " ".join(phrase.split()).casefold()


def normalize_for_autocard_match(phrase: str) -> str:
    """Match chat spans to oracle names that include commas without requiring comma tokens."""
    return normalize_phrase(phrase.replace(",", ""))


def distinct_span_phrases(
    tokens: List[str],
    max_span: int,
    blocked_normalized: AbstractSet[str],
) -> List[str]:
    """
    All distinct contiguous phrases up to ``max_span`` words, excluding blocked phrases.
    ``blocked_normalized`` contains ``normalize_phrase`` values as keys.
    """
    if not tokens:
        return []

    phrases: List[str] = []
    seen_norm: MutableSet[str] = set()

    outer_max_span = max(1, min(max_span, len(tokens)))

    for i in range(len(tokens)):
        local_max = min(outer_max_span, len(tokens) - i)

        for k in range(1, local_max + 1):
            phrase = " ".join(tokens[i : i + k])
            nl = normalize_phrase(phrase)
            if nl in blocked_normalized:
                continue
            if k == 1 and len(tokens[i]) < 2:
                continue
            if phrase.isdigit():
                continue

            if nl not in seen_norm:
                seen_norm.add(nl)
                phrases.append(phrase)

    return phrases


def greedy_resolve_cards(
    tokens: List[str],
    max_span: int,
    resolved_lower: Mapping[str, dict],
    *,
    blocked_normalized: AbstractSet[str],
    max_cards: int,
) -> List[dict]:
    """
    Greedy longest match at position ``i``: try spans ``k`` from ``min(max_span, remaining)``
    down to 1.

    Advances past consumed tokens whenever a resolving card matches, including when skipping
    a duplicate oracle (second mention uses movement only, no extra embed).
    """
    if max_cards <= 0:
        return []

    emit: List[dict] = []
    seen_oracles: MutableSet[Any] = set()

    i = 0
    while i < len(tokens) and len(emit) < max_cards:
        local_max = min(max_span, len(tokens) - i)
        consumed = False

        for k in range(local_max, 0, -1):
            phrase = " ".join(tokens[i : i + k])
            nl = normalize_phrase(phrase)
            if nl in blocked_normalized:
                continue

            card = resolved_lower.get(nl)
            if not card:
                continue

            i += k
            consumed = True

            oracle = card.get("oracle_id") or card.get("id")
            if oracle is not None:
                if oracle in seen_oracles:
                    break
                seen_oracles.add(oracle)
                emit.append(card)
            else:
                emit.append(card)
            break

        if not consumed:
            i += 1

    return emit
