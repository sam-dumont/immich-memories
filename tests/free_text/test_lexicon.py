"""The pinned WordNet corpus, read through nltk from the file `models fetch` writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.free_text.lexicon import WordNetUnavailable, load_wordnet
from tests.free_text.wordnet_corpus import write_corpus


def test_a_plural_reads_as_its_noun_and_answers_its_first_sense(tmp_path: Path) -> None:
    corpus = tmp_path / "wordnet.zip"
    digest = write_corpus(corpus, {"cat": ("noun.animal", "noun.person")})

    lexicon = load_wordnet(corpus, sha256=digest)

    assert lexicon.noun_file("cats") == "noun.animal"


def test_a_missing_corpus_names_the_command_that_fetches_it(tmp_path: Path) -> None:
    with pytest.raises(WordNetUnavailable, match="models fetch"):
        load_wordnet(tmp_path / "wordnet.zip")


def test_a_corpus_that_is_not_the_pinned_one_is_refused(tmp_path: Path) -> None:
    corpus = tmp_path / "wordnet.zip"
    write_corpus(corpus, {"cat": ("noun.animal",)})

    with pytest.raises(WordNetUnavailable, match="not the pinned WordNet corpus"):
        load_wordnet(corpus)
