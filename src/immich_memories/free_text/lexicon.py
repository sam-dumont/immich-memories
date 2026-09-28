"""English word knowledge for free-text requests: the pinned WordNet 3.0 corpus.

The corpus is the zip `immich-memories models fetch` writes (`free_text.wordnet`), checked
against its pinned digest on load. Nothing here downloads: a missing corpus is an error that
names the command to run.
"""

from __future__ import annotations

import hashlib
import warnings
from pathlib import Path
from typing import Any, Protocol

import nltk
from nltk.corpus.reader.wordnet import NOUN, WordNetCorpusReader
from nltk.data import ZipFilePathPointer

# nltk_data's `packages/corpora/wordnet.zip`, WordNet 3.0 as nltk distributes it.
WORDNET_SHA256 = "cbda5ea6eef7f36a97a43d4a75f85e07fccbb4f23657d27b4ccbc93e2646ab59"


class WordNetUnavailable(RuntimeError):
    """The corpus is missing, or is not the pinned one."""


class Lexicon(Protocol):
    """What the free-text rules ask of a dictionary."""

    def noun_file(self, word: str) -> str | None:
        """The lexicographer file of the word's first noun sense ("noun.animal"), or None."""
        ...

    def is_common_word(self, word: str) -> bool:
        """Whether the word is also an ordinary English word, not only a name."""
        ...


class _EnglishWordNet(WordNetCorpusReader):
    # nltk maps every synset onto WordNet 3.0's own ids for the multilingual data, and to do
    # that it loads a second copy of the corpus through its global search path. English needs
    # neither the map nor the second copy, and that search path is never where this corpus is.
    def map_wn(self, version: str = "wordnet") -> None:
        return None


class WordNetLexicon:
    """Answers from the WordNet corpus."""

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def noun_file(self, word: str) -> str | None:
        folded = word.strip().lower()
        base = self._reader.morphy(folded, NOUN) or folded
        senses = self._reader.synsets(base, pos=NOUN)
        return str(senses[0].lexname()) if senses else None

    def is_common_word(self, word: str) -> bool:
        # WordNet stores an ordinary word lower-case and a proper name capitalised: "meadow"
        # is a word, "Paris" a name.
        folded = "_".join(word.strip().lower().split())
        return any(
            lemma.name() == folded
            for synset in self._reader.synsets(folded)
            for lemma in synset.lemmas()
        )


def load_wordnet(path: Path, *, sha256: str = WORDNET_SHA256) -> WordNetLexicon:
    """Open the corpus zip at `path`; refuse a missing file or any other corpus."""
    corpus = path.expanduser().resolve()
    if not corpus.is_file():
        raise WordNetUnavailable(
            f"the WordNet corpus is missing at {corpus}. Run immich-memories models fetch"
        )
    with corpus.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != sha256:
        raise WordNetUnavailable(
            f"{corpus}: digest {digest[:12]} is not the pinned WordNet corpus. "
            "Run immich-memories models fetch"
        )
    # nltk reads data only from directories on its own path list.
    if str(corpus.parent) not in nltk.data.path:
        nltk.data.path.append(str(corpus.parent))
    with warnings.catch_warnings():
        # The multilingual data is not loaded, and nltk says so on every open.
        warnings.simplefilter("ignore", UserWarning)
        reader = _EnglishWordNet(ZipFilePathPointer(str(corpus), "wordnet/"), None)
    return WordNetLexicon(reader)
