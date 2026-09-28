"""A real WordNet reader over a synthetic corpus holding only the words these tests use."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.free_text.lexicon import WordNetLexicon, load_wordnet
from tests.free_text.wordnet_corpus import Sense, write_corpus

# Each word's senses as WordNet 3.0 orders them, first sense first.
VOCABULARY: dict[str, tuple[str | Sense, ...]] = {
    "cat": ("noun.animal", "noun.person"),
    "dog": ("noun.animal",),
    "car": ("noun.artifact",),
    "bread": ("noun.food",),
    "park": ("noun.location", "noun.artifact"),
    "race": ("noun.event",),
    "party": ("noun.event", Sense("verb.social", formed=("party.n.01", "partier.n.01"))),
    "partier": (Sense("noun.person", kind_of="person.n.01"),),
    "hiking": ("noun.act",),
    "hike": ("noun.act", Sense("verb.motion", formed=("hiker.n.01", "hike.n.01", "hiking.n.01"))),
    "hiker": (Sense("noun.person", kind_of="person.n.01"),),
    "making": ("noun.act",),
    "make": (Sense("verb.creation", formed=("making.n.01", "maker.n.01")),),
    "maker": (Sense("noun.person", kind_of="person.n.01"),),
    "meadow": ("noun.location",),
    "Northvale": ("noun.location",),
    "person": ("noun.person",),
    "juvenile": (Sense("noun.person", kind_of="person.n.01"),),
    "child": (
        Sense("noun.person", kind_of="juvenile.n.01", also=("kid",)),
        Sense("noun.person", kind_of="person.n.01"),
    ),
    "son": (Sense("noun.person", kind_of="child.n.02"),),
    "friend": (Sense("noun.person", kind_of="person.n.01"),),
    "spouse": (Sense("noun.person", kind_of="person.n.01", also=("partner",)),),
    "wife": (Sense("noun.person", kind_of="spouse.n.01"),),
    "time_period": ("noun.time",),
    "year": (Sense("noun.time", kind_of="time_period.n.01"),),
    "beach": ("noun.location",),
    "pool": ("noun.artifact",),
    "home": ("noun.location",),
    "eye": ("noun.body",),
    "closed": ("adj.all",),
    "rose": ("noun.plant",),
}
# Irregular plurals, as WordNet's noun.exc lists them.
EXCEPTIONS = {"children": "child"}


@pytest.fixture
def lexicon(tmp_path: Path) -> WordNetLexicon:
    corpus = tmp_path / "wordnet" / "wordnet.zip"
    return load_wordnet(corpus, sha256=write_corpus(corpus, VOCABULARY, EXCEPTIONS))
