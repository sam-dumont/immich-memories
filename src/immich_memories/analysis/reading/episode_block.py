"""One episode as the reader sees it: each fact said once, the noise left out.

An annotation line carries everything banked about a picture, including what only code reads
(resolution, exposure, subject framing, raw timestamps, pixel warnings) and the people with their
relation and age, repeated on every picture they are on. The block keeps what the picture shows
and who is on it by first name; the town, the albums and who each person is go once in the
header. Measured on a real library (#2594), the same small reader named a person or a town more
often and wrote generic sentences far less often from this block than from the raw lines.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from immich_memories.analysis.facts.line_fields import FLAGGED, PIXEL_WARNINGS

# The People line names this many, the ones on the most pictures: nine names there got all nine
# named in the answer.
_PEOPLE_SHOWN = 4
_WHEN = re.compile(r"^(\d{4}-\d\d-\d\d)[ T]\d\d:\d\d")
_COORDINATES = re.compile(r"^-?\d+(?:\.\d+)?$")
_HEADS = re.compile(r"^[a-z_-]+=\S")
# Read by code only: the source's technical facts (`resolution:4032x3024`, `duration:3.000s`,
# `subject-framing:close (...)`), the caption producer's exposure, and the pixel warnings.
_NOISE = re.compile(
    r"^(?:[a-z][a-z-]*:\S|exposure: |reencode-suspected$"
    rf"|(?:{'|'.join(re.escape(warning) for warning in PIXEL_WARNINGS)})$)"
)
_HEAD_WORDS = {
    "eating-drinking": "a meal",
    "sport-active": "sport",
    "animal-nature": "animals",
    "water": "by the water",
}
_HEAD_SILENT_VALUES = frozenset({"posing", "working"})
_HEAD_SILENT_KEYS = frozenset({"location", "people", "children"})
_TIER_WORDS = frozenset({"inner circle"})


@dataclass
class _Picture:
    said: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    people: list[tuple[str, str]] = field(default_factory=list)
    town: str = ""
    day: str = ""

    def line(self, number: int) -> str:
        text = "; ".join(dict.fromkeys(self.said)) or "no description"
        extra = list(dict.fromkeys(self.tags))
        if self.people:
            extra.append("with " + ", ".join(dict.fromkeys(name for name, _ in self.people)))
        return f"{number}. {text}" + ("; " + "; ".join(extra) if extra else "")


def picture_line(number: int, line: str) -> str:
    """One picture's line in the block, numbered as the answer names it."""
    return _read(line).line(number)


def people_on(lines: Sequence[str]) -> str:
    """Who is on these pictures, as the block's People line names them: the four on the most
    pictures by first name with who they are, then how many others."""
    return _who([_read(line) for line in lines])


def episode_block(
    lines: Sequence[str],
    *,
    albums: Sequence[str] = (),
    page: tuple[int, int] | None = None,
) -> str:
    """The block for one episode (or one page of it): a header of facts said once, then a
    numbered line per picture."""
    pictures = [_read(line) for line in lines]
    head = [_episode_line(pictures, page)]
    towns = dict.fromkeys(picture.town for picture in pictures if picture.town)
    if towns:
        head.append("Town: " + "; ".join(towns))
    if albums:
        head.append("Albums: " + "; ".join(albums))
    people = _who(pictures)
    if people:
        head.append("People: " + people)
    numbered = (picture.line(number) for number, picture in enumerate(pictures, start=1))
    return "\n".join((*head, "Pictures:", *numbered))


def _episode_line(pictures: Sequence[_Picture], page: tuple[int, int] | None) -> str:
    count = len(pictures)
    days = sorted(picture.day for picture in pictures if picture.day)
    when = ""
    if days:
        when = f", {days[0]}" if days[0] == days[-1] else f", {days[0]} to {days[-1]}"
    part = f" (page {page[0]} of {page[1]})" if page is not None else ""
    return f"EPISODE: {count} picture{'' if count == 1 else 's'}{when}{part}"


def _who(pictures: Sequence[_Picture]) -> str:
    seen: Counter[str] = Counter()
    about: dict[str, str] = {}
    for picture in pictures:
        for name, said in picture.people:
            seen[name] += 1
            about.setdefault(name, said)
    if not seen:
        return ""
    shown = [name for name, _count in seen.most_common(_PEOPLE_SHOWN)]
    line = "; ".join(f"{name} ({about[name]})" if about[name] else name for name in shown)
    others = len(seen) - len(shown)
    return f"{line}; and {others} others" if others else line


def _read(line: str) -> _Picture:
    picture = _Picture()
    for part in (part.strip() for part in line.split(" | ")):
        if not part or _NOISE.match(part):
            continue
        when = _WHEN.match(part)
        if when:
            picture.day = when.group(1)
        else:
            _read_part(picture, part)
    return picture


def _read_part(picture: _Picture, part: str) -> None:
    if part.startswith("with "):
        picture.people = [_person(person) for person in _people(part[len("with ") :])]
    elif part.startswith("at "):
        town = part[len("at ") :].split(",")[0].strip()
        if town and not _COORDINATES.match(town):
            picture.town = town
    elif part.startswith("setting:"):
        picture.tags.append(part.split(":", 1)[1].strip().rstrip("."))
    elif _HEADS.match(part):
        picture.tags.extend(_head_words(part))
    elif tag := _media_tag(part):
        picture.tags.append(tag)
    else:
        picture.said.append(part.rstrip("."))


def _media_tag(part: str) -> str:
    if part.startswith("STARRED"):
        return "starred"
    if part.startswith("VIDEO"):
        return "a video"
    if part.startswith("LIVE PHOTO"):
        return "a live photo"
    if part.startswith(FLAGGED):
        return "flagged"
    return ""


def _head_words(part: str) -> list[str]:
    """The detector heads a reader can use, in words: `activity=eating-drinking` is a meal."""
    words = []
    for pair in part.split(", "):
        key, _, value = pair.partition("=")
        if key in _HEAD_SILENT_KEYS or not value or value in _HEAD_SILENT_VALUES:
            continue
        words.append(_HEAD_WORDS.get(value, value) if key in ("activity", "venue") else pair)
    return words


def _people(text: str) -> list[str]:
    """`A (x; y); B (z)` is `A (x; y)` and `B (z)`: split on the semicolons outside brackets."""
    found, depth, current = [], 0, ""
    for character in text:
        depth += (character == "(") - (character == ")")
        if character == ";" and depth == 0:
            found.append(current.strip())
            current = ""
        else:
            current += character
    if current.strip():
        found.append(current.strip())
    return found


def _person(text: str) -> tuple[str, str]:
    """A person's first name, and who they are with their tier left out."""
    name, _, rest = text.partition(" (")
    words = name.split()
    about = ", ".join(
        bit for bit in rest.removesuffix(")").split("; ") if bit and bit not in _TIER_WORDS
    )
    return (words[0] if words else name), about
