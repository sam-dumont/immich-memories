"""A real WordNet reader over a synthetic corpus holding only the words these tests use."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.free_text.lexicon import WordNetLexicon, load_wordnet
from tests.free_text.wordnet_corpus import write_corpus

# Each word's senses as WordNet 3.0 orders them, first sense first.
VOCABULARY = {
    "cat": ("noun.animal", "noun.person"),
    "dog": ("noun.animal",),
    "car": ("noun.artifact",),
    "bread": ("noun.food",),
    "park": ("noun.location", "noun.artifact"),
    "race": ("noun.event",),
    "party": ("noun.event",),
    "hiking": ("noun.act",),
    "meadow": ("noun.location",),
    "Northvale": ("noun.location",),
}


@pytest.fixture
def lexicon(tmp_path: Path) -> WordNetLexicon:
    corpus = tmp_path / "wordnet" / "wordnet.zip"
    return load_wordnet(corpus, sha256=write_corpus(corpus, VOCABULARY))
