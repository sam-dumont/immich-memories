"""A WordNet corpus small enough to write in a test, laid out the way the pinned zip is.

The real corpus is 11 MB and fetched by `models fetch`, so it never sits in the repo. This
writes the same files (`lexnames`, `index.*`, `data.*`, `*.exc`) with only the words a test
names, each synset at its true byte offset, so nltk's own reader parses it unchanged.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping, Sequence
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
    "noun.body",
    "verb.motion",
    "verb.social",
    "verb.creation",
)
# WordNet's file suffix per part of speech.
_FILES = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}

# (pointer symbol, target sense number, the source/target lemma field)
_Pointer = tuple[str, int, str]


@dataclass(frozen=True)
class Sense:
    """One sense: its file, and the synsets it points to, named the way nltk names them.

    `kind_of` is the synset it is a kind of ("person.n.01"); the kind's own line points back.
    `parts` are its own parts ("wheel.n.01"). `formed` are the synsets derived from its first
    lemma ("hiker.n.01" from the verb "hike"), pointed to both ways as WordNet does.
    """

    lexname: str
    kind_of: str | None = None
    also: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()
    formed: tuple[str, ...] = ()

    @property
    def pos(self) -> str:
        return {"noun": "n", "verb": "v", "adj": "a"}[self.lexname.split(".")[0]]


def write_corpus(
    path: Path,
    words: Mapping[str, tuple[str | Sense, ...]],
    exceptions: Mapping[str, str] | None = None,
) -> str:
    """Write the zip at `path`; return its SHA-256.

    `words` maps a lemma as WordNet stores it ("cat", "Paris") to each of its senses, most
    common first per part of speech: a lexicographer file ("noun.animal", "verb.motion",
    "adj.all") or a `Sense`. `exceptions` maps an irregular plural to its noun ("children":
    "child").
    """
    senses = [
        (lemma, sense if isinstance(sense, Sense) else Sense(sense))
        for lemma, found in words.items()
        for sense in found
    ]
    names: dict[tuple[str, str], list[int]] = {}
    for number, (lemma, sense) in enumerate(senses):
        for name in (lemma, *sense.also):
            names.setdefault((sense.pos, name.lower()), []).append(number)
    pointers = _pointers(senses, names)
    positions = [sense.pos for _, sense in senses]
    # Every field has a fixed width, so each line's length (and so each offset) is known before
    # the offsets it points to are.
    blank = [0] * len(senses)
    offsets: list[int] = []
    size = dict.fromkeys(_FILES, 0)
    for number, (lemma, sense) in enumerate(senses):
        offsets.append(size[sense.pos])
        line = _line(lemma, sense, pointers[number], blank, positions)
        size[sense.pos] += len(line.encode())
    files = {"lexnames": "".join(f"{n:02d} {name} 1\n" for n, name in enumerate(LEXNAMES))}
    for pos, suffix in _FILES.items():
        files[f"data.{suffix}"] = "".join(
            _line(lemma, sense, pointers[number], offsets, positions, offsets[number])
            for number, (lemma, sense) in enumerate(senses)
            if sense.pos == pos
        )
        files[f"index.{suffix}"] = "".join(
            f"{name} {pos} {len(found)} 0 {len(found)} 0 "
            f"{' '.join(f'{offsets[n]:08d}' for n in found)}\n"
            for (found_pos, name), found in sorted(names.items())
            if found_pos == pos
        )
        files[f"{suffix}.exc"] = ""
    files["noun.exc"] = "".join(f"{plural} {noun}\n" for plural, noun in (exceptions or {}).items())
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("wordnet/", "")
        for name, text in files.items():
            archive.writestr(f"wordnet/{name}", text)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pointers(
    senses: Sequence[tuple[str, Sense]], names: Mapping[tuple[str, str], list[int]]
) -> list[list[_Pointer]]:
    def target(synset: str) -> int:
        lemma, pos, number = synset.rsplit(".", 2)
        return names[(pos, lemma.lower())][int(number) - 1]

    pointers: list[list[_Pointer]] = [[] for _ in senses]
    for number, (_, sense) in enumerate(senses):
        if sense.kind_of:
            kind = target(sense.kind_of)
            pointers[number].append(("@", kind, "0000"))
            pointers[kind].append(("~", number, "0000"))
        for part in sense.parts:
            pointers[number].append(("%p", target(part), "0000"))
            pointers[target(part)].append(("#p", number, "0000"))
        for formed in sense.formed:
            for source, other in ((number, target(formed)), (target(formed), number)):
                if ("+", other, "0101") not in pointers[source]:
                    pointers[source].append(("+", other, "0101"))
    return pointers


def _line(
    lemma: str,
    sense: Sense,
    pointers: Sequence[_Pointer],
    offsets: Sequence[int],
    positions: Sequence[str],
    offset: int = 0,
) -> str:
    lemmas = (lemma, *sense.also)
    words = " ".join(f"{name} 0" for name in lemmas)
    listed = "".join(
        f" {symbol} {offsets[target]:08d} {positions[target]} {field}"
        for symbol, target, field in pointers
    )
    return (
        f"{offset:08d} {LEXNAMES.index(sense.lexname):02d} {sense.pos} {len(lemmas):02x} {words} "
        f"{len(pointers):03d}{listed} | a test sense\n"
    )
