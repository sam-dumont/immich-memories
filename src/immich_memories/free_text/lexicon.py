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
from nltk.corpus.reader.wordnet import ADJ, NOUN, VERB, WordNetCorpusReader
from nltk.data import ZipFilePathPointer

# The synsets whose kinds are people: a person, people as a whole, a group of people.
_HUMAN = frozenset({"person.n.01", "people.n.01", "social_group.n.01"})
# A young person, and someone's child: WordNet files a baby under offspring, not juvenile.
_YOUNG = frozenset({"juvenile.n.01", "child.n.02"})
_TIME_PERIOD = "time_period.n.01"

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

    def noun_base(self, word: str) -> str | None:
        """The noun a word is a form of ("children": "child"), or None when it is no noun."""
        ...

    def is_human(self, word: str) -> bool:
        """Whether the word's first noun sense is a kind of person, people or social group."""
        ...

    def is_young(self, word: str) -> bool:
        """Whether the word's first noun sense is a young person or someone's child."""
        ...

    def is_time_period(self, word: str) -> bool:
        """Whether the word's first noun sense is a period of time ("years", "summers")."""
        ...

    def names_role(self, word: str, role: str) -> bool:
        """Whether the word names a people-file role: the role itself or a kind of it."""
        ...

    def verb_base(self, word: str) -> str | None:
        """The verb a word is a form of ("hiking": "hike"), or None when it is no verb."""
        ...

    def is_adjective(self, word: str) -> bool:
        """Whether WordNet holds the word as an adjective ("black", "closed", "live")."""
        ...

    def derived_nouns(self, word: str) -> frozenset[str]:
        """The nouns WordNet forms from the word as a noun or a verb, its own noun included.

        "hiking" gives hiking, hike and hiker; "partying" (no noun) gives party and partier.
        """
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

    def noun_base(self, word: str) -> str | None:
        folded = word.strip().lower()
        base = self._reader.morphy(folded, NOUN)
        return str(base) if base else None

    def is_human(self, word: str) -> bool:
        return bool(self._kinds(word) & _HUMAN)

    def is_young(self, word: str) -> bool:
        return bool(self._kinds(word) & _YOUNG)

    def is_time_period(self, word: str) -> bool:
        return _TIME_PERIOD in self._kinds(word)

    def names_role(self, word: str, role: str) -> bool:
        wanted = " ".join(role.lower().split())
        base = self.noun_base(word) or word.strip().lower()
        if base in {wanted, wanted.split()[-1] if wanted else ""}:
            return True
        # The first two senses: "wife" is a spouse, whose names include "partner".
        return any(
            lemma.name().lower().replace("_", " ") == wanted
            for sense in self._reader.synsets(base, pos=NOUN)[:2]
            for synset in (sense, *sense.hypernyms())
            for lemma in synset.lemmas()
        )

    def verb_base(self, word: str) -> str | None:
        base = self._reader.morphy(word.strip().lower(), VERB)
        return str(base) if base else None

    def is_adjective(self, word: str) -> bool:
        return bool(self._reader.synsets(word.strip().lower(), pos=ADJ))

    def derived_nouns(self, word: str) -> frozenset[str]:
        found: set[str] = set()
        noun = self.noun_base(word)
        if noun:
            found.add(noun)
        for base, pos in ((noun, NOUN), (self.verb_base(word), VERB)):
            if not base:
                continue
            found |= {
                formed.name().lower()
                for synset in self._reader.synsets(base, pos=pos)
                for lemma in synset.lemmas()
                if lemma.name().lower() == base
                for formed in lemma.derivationally_related_forms()
                if formed.synset().pos() == NOUN
            }
        return frozenset(found)

    def _kinds(self, word: str) -> set[str]:
        base = self.noun_base(word) or word.strip().lower()
        return {
            str(kind.name())
            for sense in self._reader.synsets(base, pos=NOUN)[:1]
            for path in sense.hypernym_paths()
            for kind in path
        }


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
