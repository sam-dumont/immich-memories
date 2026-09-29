"""The pinned WordNet corpus, read through nltk from the file `models fetch` writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.free_text.lexicon import WordNetLexicon, WordNetUnavailable, load_wordnet
from tests.free_text.wordnet_corpus import Sense, write_corpus


def test_a_plural_reads_as_its_noun_and_answers_its_first_sense(tmp_path: Path) -> None:
    corpus = tmp_path / "wordnet.zip"
    digest = write_corpus(corpus, {"cat": ("noun.animal", "noun.person")})

    lexicon = load_wordnet(corpus, sha256=digest)

    assert lexicon.noun_file("cats") == "noun.animal"


def test_a_word_is_common_only_when_wordnet_stores_it_lower_case(tmp_path: Path) -> None:
    corpus = tmp_path / "wordnet.zip"
    digest = write_corpus(corpus, {"meadow": ("noun.location",), "Northvale": ("noun.location",)})

    lexicon = load_wordnet(corpus, sha256=digest)

    assert lexicon.is_common_word("Meadow")
    assert not lexicon.is_common_word("Northvale")


def test_a_missing_corpus_names_the_command_that_fetches_it(tmp_path: Path) -> None:
    with pytest.raises(WordNetUnavailable, match="models fetch"):
        load_wordnet(tmp_path / "wordnet.zip")


def test_a_corpus_that_is_not_the_pinned_one_is_refused(tmp_path: Path) -> None:
    corpus = tmp_path / "wordnet.zip"
    write_corpus(corpus, {"cat": ("noun.animal",)})

    with pytest.raises(WordNetUnavailable, match="not the pinned WordNet corpus"):
        load_wordnet(corpus)


def _people_words(tmp_path: Path) -> WordNetLexicon:
    corpus = tmp_path / "wordnet.zip"
    digest = write_corpus(
        corpus,
        {
            "person": ("noun.person",),
            "juvenile": (Sense("noun.person", kind_of="person.n.01"),),
            "child": (
                Sense("noun.person", kind_of="juvenile.n.01", also=("kid",)),
                Sense("noun.person", kind_of="person.n.01"),
            ),
            "baby": (Sense("noun.person", kind_of="child.n.02"),),
            "friend": (Sense("noun.person", kind_of="person.n.01"),),
            "spouse": (Sense("noun.person", kind_of="person.n.01", also=("partner",)),),
            "wife": (Sense("noun.person", kind_of="spouse.n.01"),),
            "car": ("noun.artifact",),
            "time_period": ("noun.time",),
            "year": (Sense("noun.time", kind_of="time_period.n.01"),),
        },
        exceptions={"children": "child"},
    )
    return load_wordnet(corpus, sha256=digest)


def test_people_words_are_told_from_things_through_their_kinds(tmp_path: Path) -> None:
    lexicon = _people_words(tmp_path)

    assert lexicon.is_human("friends")
    assert not lexicon.is_human("cars")


def test_young_people_are_juveniles_or_offspring(tmp_path: Path) -> None:
    lexicon = _people_words(tmp_path)

    assert lexicon.is_young("children")
    assert lexicon.is_young("kids")
    assert lexicon.is_young("babies")
    assert not lexicon.is_young("friends")


def test_a_plural_is_told_by_its_noun_base(tmp_path: Path) -> None:
    lexicon = _people_words(tmp_path)

    assert lexicon.noun_base("children") == "child"
    assert lexicon.noun_base("car") == "car"
    assert lexicon.noun_base("xyzzy") is None


def test_a_time_period_is_one_of_wordnets_time_periods(tmp_path: Path) -> None:
    lexicon = _people_words(tmp_path)

    assert lexicon.is_time_period("years")
    assert not lexicon.is_time_period("cars")


def test_a_word_names_a_role_by_itself_or_through_its_kind(tmp_path: Path) -> None:
    lexicon = _people_words(tmp_path)

    assert lexicon.names_role("wife", "partner")
    assert lexicon.names_role("wife", "wife")
    assert not lexicon.names_role("friend", "partner")
