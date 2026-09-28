"""A WordNet corpus small enough to write in a test, laid out the way the pinned zip is.

The real corpus is 11 MB and fetched by `models fetch`, so it never sits in the repo. This
writes the same files (`lexnames`, `index.*`, `data.*`, `*.exc`) with only the nouns a test
names, each synset at its true byte offset, so nltk's own reader parses it unchanged.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
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
)


def write_corpus(path: Path, nouns: Mapping[str, tuple[str, ...]]) -> str:
    """Write the zip at `path`; return its SHA-256.

    `nouns` maps a lemma as WordNet stores it ("cat", "Paris") to the lexicographer file of
    each of its senses, most common first.
    """
    data = ""
    offsets: dict[str, list[int]] = {}
    for lemma, senses in nouns.items():
        for lexname in senses:
            offset = len(data.encode())
            data += (
                f"{offset:08d} {LEXNAMES.index(lexname):02d} n 01 {lemma} 0 000 | a test sense\n"
            )
            offsets.setdefault(lemma.lower(), []).append(offset)
    index = "".join(
        f"{lemma} n {len(found)} 0 {len(found)} 0 {' '.join(f'{o:08d}' for o in found)}\n"
        for lemma, found in sorted(offsets.items())
    )
    files = {
        "lexnames": "".join(f"{n:02d} {name} 1\n" for n, name in enumerate(LEXNAMES)),
        "index.noun": index,
        "data.noun": data,
        **{f"index.{pos}": "" for pos in ("verb", "adj", "adv")},
        **{f"data.{pos}": "" for pos in ("verb", "adj", "adv")},
        **{f"{pos}.exc": "" for pos in ("noun", "verb", "adj", "adv")},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("wordnet/", "")
        for name, text in files.items():
            archive.writestr(f"wordnet/{name}", text)
    return hashlib.sha256(path.read_bytes()).hexdigest()
