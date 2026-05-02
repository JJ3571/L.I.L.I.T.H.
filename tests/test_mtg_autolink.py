"""Unit tests for MTG autolink tokenization and greedy resolution."""

import pytest

from main_bot.utils.mtg_autolink import distinct_span_phrases
from main_bot.utils.mtg_autolink import greedy_resolve_cards
from main_bot.utils.mtg_autolink import normalize_for_autocard_match
from main_bot.utils.mtg_autolink import normalize_phrase
from main_bot.utils.mtg_autolink import tokenize


def test_normalize_phrase_collapses_spaces_and_casefolds():
    assert normalize_phrase("  Lightning   Bolt ") == "lightning bolt"
    assert normalize_phrase("ANGER") == "anger"


def test_normalize_for_autocard_match_drops_commas_for_lookup():
    assert normalize_for_autocard_match("Shabraz, the Skyshark") == normalize_phrase("Shabraz the Skyshark")


def test_tokenize_strips_words_from_punctuation_and_keeps_apostrophe():
    assert tokenize("I cast Anger!") == ["I", "cast", "Anger"]
    assert tokenize("Ajani's Pridemate.") == ["Ajani's", "Pridemate"]


@pytest.mark.parametrize(
    ("content", "max_span"),
    [
        ("a b", 2),
        ("one two three four five", 4),
    ],
)
def test_distinct_span_phrases_bounded_by_max_span(content, max_span):
    tokens = tokenize(content)
    phrases = distinct_span_phrases(tokens, max_span, frozenset())
    max_words = max(p.count(" ") + 1 for p in phrases) if phrases else 0
    assert max_words <= max_span


def test_distinct_span_phrases_excludes_blocked():
    tokens = tokenize("Anger is real")
    blocked = frozenset({normalize_phrase("Anger"), normalize_phrase("is")})
    phrases = distinct_span_phrases(tokens, 4, blocked)
    lowers = {normalize_phrase(p) for p in phrases}
    assert normalize_phrase("Anger") not in lowers
    assert normalize_phrase("is") not in lowers
    assert normalize_phrase("real") in lowers


def test_distinct_span_phrases_single_char_token_skipped_when_k_is_one():
    tokens = ["a"]
    phrases = distinct_span_phrases(tokens, 2, frozenset())
    assert phrases == []

    phrases2 = distinct_span_phrases(["Ok", "a"], 2, frozenset())
    lowers2 = {normalize_phrase(p) for p in phrases2}
    assert normalize_phrase("Ok a") in lowers2


def test_greedy_resolve_legend_with_comma_in_title_chat_has_no_commas_between_tokens():
    """Tokenizer omits commas, so lookups need a comma-stripped alias keyed like Scryfall fill."""
    shabraz = {
        "name": "Shabraz, the Skyshark",
        "oracle_id": "shabraz",
        "type_line": "Creature — Shark",
        "set_name": "Test",
    }
    canonical = normalize_phrase(shabraz["name"])
    stripped = normalize_for_autocard_match(shabraz["name"])
    resolved = {canonical: shabraz, stripped: shabraz}

    out = greedy_resolve_cards(
        tokenize("I love Shabraz the Skyshark"),
        max_span=8,
        resolved_lower=resolved,
        blocked_normalized=frozenset(),
        max_cards=10,
    )
    assert len(out) == 1
    assert out[0]["name"] == "Shabraz, the Skyshark"


def test_greedy_longest_prefers_two_word_name_over_single_where_both_resolve():
    """Resolve the longest span starting at ``i`` when multiple names match."""

    resolved = {
        normalize_phrase("Lightning Bolt"): {
            "name": "Lightning Bolt",
            "oracle_id": "obolt",
        },
        normalize_phrase("Bolt"): {
            "name": "Bolt",
            "oracle_id": "odash",
        },
    }

    out = greedy_resolve_cards(
        ["Lightning", "Bolt"],
        max_span=3,
        resolved_lower=resolved,
        blocked_normalized=frozenset(),
        max_cards=10,
    )
    assert len(out) == 1
    assert out[0]["oracle_id"] == "obolt"


def test_greedy_duplicate_second_mention_moves_without_extra_embed():
    anger = {"name": "Anger", "oracle_id": "o-a", "type_line": "Enchantment", "set_name": "Test"}
    resolved = {normalize_phrase("Anger"): anger}

    tokens = ["Anger", "and", "Anger"]
    out = greedy_resolve_cards(
        tokens, 4, resolved, blocked_normalized=frozenset(), max_cards=10
    )
    assert len(out) == 1


def test_greedy_two_distinct_cards_in_order():
    a = {"name": "A", "oracle_id": "1", "type_line": "X", "set_name": "S"}
    b = {"name": "B", "oracle_id": "2", "type_line": "Y", "set_name": "S"}
    resolved = {
        normalize_phrase("A"): a,
        normalize_phrase("B"): b,
    }

    tokens = ["A", "B"]
    out = greedy_resolve_cards(
        tokens, 4, resolved, blocked_normalized=frozenset(), max_cards=10
    )
    assert out[0]["oracle_id"] == "1"
    assert out[1]["oracle_id"] == "2"


def test_max_cards_truncates_remaining():
    anger = {"name": "Anger", "oracle_id": "a", "type_line": "E", "set_name": "S"}
    resolved = {normalize_phrase("Anger"): anger}

    tokens = ["Anger", "Anger"]
    out = greedy_resolve_cards(
        tokens, 4, resolved, blocked_normalized=frozenset(), max_cards=1
    )
    assert len(out) == 1


def test_blocklist_prevents_resolve_even_if_in_scryfall_map():
    anger = {"name": "Anger", "oracle_id": "a", "type_line": "E", "set_name": "S"}
    resolved = {normalize_phrase("Anger"): anger}
    blocked = frozenset({normalize_phrase("Anger")})

    out = greedy_resolve_cards(
        ["Anger"], 4, resolved, blocked_normalized=blocked, max_cards=10
    )
    assert out == []
