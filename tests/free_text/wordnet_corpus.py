"""A WordNet corpus small enough to write in a test, laid out the way the pinned zip is.

The real corpus is 11 MB and fetched by `models fetch`, so it never sits in the repo. This
writes the same files (`lexnames`, `index.*`, `data.*`, `*.exc`) with only the nouns a test
names, each synset at its true byte offset, so nltk's own reader parses it unchanged.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LEXNAMES = (
    "adj.all",
    "noun.act",
    "noun.animal",
    "noun.artifact",
    "noun.cognition",
    "noun.event",
    "noun.food",
    "noun.location",
    "noun.person",
    "noun.plant",
    "noun.state",
    "noun.substance",
    "noun.time",
)


@dataclass(frozen=True)
class Sense:
    """One noun sense: its file, the synset it is a kind of ("person.n.01"), its other lemmas."""

    lexname: str
    kind_of: str | None = None
    also: tuple[str, ...] = ()


def write_corpus(
    path: Path,
    nouns: Mapping[str, tuple[str | Sense, ...]],
    exceptions: Mapping[str, str] | None = None,
) -> str:
    """Write the zip at `path`; return its SHA-256.

    `nouns` maps a lemma as WordNet stores it ("cat", "Paris") to each of its senses, most
    common first: a lexicographer file, or a `Sense` with the synset it is a kind of (named
    the way nltk names it, "lemma.n.NN") and the synset's other lemmas. `exceptions` maps an
    irregular plural to its noun ("children": "child").
    """
    senses = [
        (lemma, sense if isinstance(sense, Sense) else Sense(sense))
        for lemma, found in nouns.items()
        for sense in found
    ]
    # Every field has a fixed width, so each line's length (and so each offset) is known before
    # the offsets it points to are.
    offsets: list[int] = []
    size = 0
    for lemma, sense in senses:
        offsets.append(size)
        size += len(_line(0, lemma, sense, 0 if sense.kind_of else None).encode())
    names: dict[str, list[int]] = {}
    for (lemma, sense), offset in zip(senses, offsets, strict=True):
        for name in (lemma, *sense.also):
            names.setdefault(name.lower(), []).append(offset)
    data = "".join(
        _line(offset, lemma, sense, _target(sense.kind_of, names))
        for (lemma, sense), offset in zip(senses, offsets, strict=True)
    )
    index = "".join(
        f"{lemma} n {len(found)} 0 {len(found)} 0 {' '.join(f'{o:08d}' for o in found)}\n"
        for lemma, found in sorted(names.items())
    )
    files = {
        "lexnames": "".join(f"{n:02d} {name} 1\n" for n, name in enumerate(LEXNAMES)),
        "index.noun": index,
        "data.noun": data,
        "noun.exc": "".join(f"{plural} {noun}\n" for plural, noun in (exceptions or {}).items()),
        **{f"index.{pos}": "" for pos in ("verb", "adj", "adv")},
        **{f"data.{pos}": "" for pos in ("verb", "adj", "adv")},
        **{f"{pos}.exc": "" for pos in ("verb", "adj", "adv")},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("wordnet/", "")
        for name, text in files.items():
            archive.writestr(f"wordnet/{name}", text)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target(kind_of: str | None, names: Mapping[str, list[int]]) -> int | None:
    if kind_of is None:
        return None
    lemma, _, number = kind_of.rsplit(".", 2)
    return names[lemma.lower()][int(number) - 1]


def _line(offset: int, lemma: str, sense: Sense, kind_of: int | None) -> str:
    lemmas = (lemma, *sense.also)
    words = " ".join(f"{name} 0" for name in lemmas)
    pointer = "000" if kind_of is None else f"001 @ {kind_of:08d} n 0000"
    return (
        f"{offset:08d} {LEXNAMES.index(sense.lexname):02d} n {len(lemmas):02x} {words} "
        f"{pointer} | a test sense\n"
    )
