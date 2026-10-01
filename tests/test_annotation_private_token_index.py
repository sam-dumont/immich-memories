"""Indexed annotation privacy checks preserve literal substring decisions."""

import random
import string

import pytest

from immich_memories.analysis.private_token_matcher import private_token_matcher


@pytest.mark.parametrize(
    ("tokens", "text", "expected"),
    [
        ([], "anything", False),
        ([""], "", True),
        (["abcdef12"], "prefixABCDEF12suffix", True),
        (["abcdefgh-one", "abcdefgh-two"], "abcdefgh-three", False),
        (["abcdefgh-one", "abcdefgh-two"], "xabcdefgh-two!", True),
        (["abcdefgh", "abcdefgh-long"], "abcdefgh-short", True),
        (["strasse-identifier"], "Die STRAẞE-IDENTIFIER!", True),
        (["12345678"], "1234567", False),
        (["12345678"], "one 12345678", True),
        (["aaaabbbbcccc"], "aaaaaaaabbbbcccc", True),
    ],
)
def test_literal_matching_boundaries(tokens, text, expected):
    assert private_token_matcher(frozenset(tokens))(text) is expected


def test_index_matches_original_search_across_overlaps_casefold_and_token_lengths():
    rng = random.Random(2024)
    alphabet = string.ascii_lowercase + string.digits + "-_ßé"
    for _ in range(60):
        tokens = frozenset(
            "".join(rng.choices(alphabet, k=rng.randrange(0, 45))).casefold() for _ in range(35)
        )
        contains = private_token_matcher(tokens)
        for _ in range(20):
            text = "".join(rng.choices(alphabet, k=90))
            if rng.random() < 0.5:
                text = text[:30] + rng.choice(sorted(tokens)).upper() + text[30:]
            assert contains(text) == any(token in text.casefold() for token in tokens)


def test_non_identifier_prose_does_not_allocate_a_prefix_at_every_character():
    class CountedText(str):
        slices = 0

        def casefold(self):
            return self

        def __getitem__(self, key):
            if isinstance(key, slice):
                self.slices += 1
            return super().__getitem__(key)

    text = CountedText("a child with a kite on the beach " * 100)
    contains = private_token_matcher(frozenset({"01234567", "89abcdef-long"}))
    assert not contains(text)
    assert text.slices == 0


@pytest.mark.parametrize(
    ("tokens", "text"),
    [
        ({"[]\\^-.*abcdefgh"}, "prefix[]\\^-.*abcdefgh suffix"),
        ({"01234567-tail", "12345678-tail"}, "0012345678-tail"),
        ({"café-東京-private", "strasse-identifier"}, "STRASSE-IDENTIFIER"),
        ({"a", "a-long-token"}, "a-different-tail"),
        ({"12345678-long"}, "12345678-other"),
        ({"\nprivate-token"}, "before\nprivate-token"),
    ],
)
def test_candidate_scan_keeps_literal_punctuation_and_overlapping_prefixes(tokens, text):
    expected = any(token in text.casefold() for token in tokens)
    assert private_token_matcher(frozenset(tokens))(text) is expected
