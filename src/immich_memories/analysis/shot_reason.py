"""Why a shot is in the cut, in the words a person would write (#2487).

A shot's reason is built from its own facts, read off its annotation line: who is on it (the
people the line names), what it shows (the caption, when the picture has one) or else where it was
taken, and what made it beat the rest of its moment: a star, the owner keeping it, motion, the
only frame with its people, the clearest view of them, the sharpest of its run.

It never carries what the pipeline wrote for itself: timestamps, detector heads, subject-framing
percentages, resolutions, the media tag, or a reader's own words such as "capture group". It
never repeats the story's title, and names a place only when the story's name doesn't.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from immich_memories.analysis.annotation_line_fields import content_of
from immich_memories.analysis.subject_framing import framing_visibility

REASON_CHARS = 80
SEPARATOR = " · "
# A picture the planner plays as motion; any other kind is held as a still.
_LIVE_MOTION = frozenset({"live-motion", "motion"})
_SOFT = "SOFT (blurry)"
_ROW_PREFIX = re.compile(r"^Material picture p\d+: ")
_COORDINATES = re.compile(r"^-?\d")
# Opening words a caption starts a sentence with; lowered, the caption reads on after a name.
_OPENERS = frozenset({"a", "an", "the", "one", "two", "three", "four", "five", "several", "some"})
# A name a person gives a story is short; a longer one lists everything and names no place.
_STORY_NAME_CHARS = 40
_SHOWN_NAMES = 2
_MAX_BEATS = 2

_TELEMETRY = re.compile(
    r"capture group"
    r"|\d{4}-\d\d-\d\d[ T]\d\d:\d\d"  # a capture timestamp
    r"|\b[a-z_]+=\S"  # a detector head, `activity=posing`
    r"|\b[a-z][a-z-]*:\S"  # a technical fact, `resolution:1280x960`, `subject-framing:2`
    r"|% of the frame"
    r"|\bVIDEO \d+s raw\b"
    r"|\d{3,5}x\d{3,5}"
    r"| \| "  # the annotation line's own field separator
)


def reads_as_telemetry(text: str) -> bool:
    """Whether a reason carries what the pipeline wrote for itself rather than words."""
    return bool(_TELEMETRY.search(text))


@dataclass(frozen=True, slots=True)
class _Facts:
    names: tuple[str, ...]
    place: str
    caption: str
    video: bool
    burst: bool


def _segments(line: str) -> list[str]:
    return [
        part.strip()
        for row in line.splitlines()
        for part in _ROW_PREFIX.sub("", row.strip()).split(" | ")
        if part.strip()
    ]


def _split_people(listed: str) -> list[str]:
    """The names a line's `with A (note; note); B` part lists, notes dropped."""
    names, depth, current = [], 0, ""
    for char in listed:
        depth += (char == "(") - (char == ")")
        if char == ";" and depth == 0:
            names.append(current)
            current = ""
        else:
            current += char
    names.append(current)
    return [name.split("(")[0].strip() for name in names if name.split("(")[0].strip()]


def _caption(line: str) -> str:
    for part in content_of(line).split(" | "):
        part = " ".join(part.split()).rstrip(".")
        if part and not part.startswith(("setting:", "exposure:")) and not reads_as_telemetry(part):
            first, _, rest = part.partition(" ")
            return f"{first.lower()} {rest}".strip() if first.casefold() in _OPENERS else part
    return ""


def _read(line: str) -> _Facts:
    segments = _segments(line)
    names: list[str] = []
    place = ""
    for part in segments:
        if part.startswith("with "):
            names += [n for n in _split_people(part[5:]) if n not in names]
        elif part.startswith("at ") and not place:
            town = part[3:].split(",")[0].strip()
            place = "" if _COORDINATES.match(town) else town
    return _Facts(
        names=tuple(names),
        place=place,
        caption=_caption(line),
        video=any(part.startswith("VIDEO") for part in segments),
        burst="LIVE PHOTO BURST" in line,
    )


def _who(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    if len(names) <= _SHOWN_NAMES + 1:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{', '.join(names[:_SHOWN_NAMES])} and {len(names) - _SHOWN_NAMES} others"


def _motion(facts: _Facts, kind: str) -> str:
    if kind == "video" or facts.video:
        return "video"
    if kind in _LIVE_MOTION:
        return "Live Photo burst" if facts.burst else "Live Photo"
    return ""


def _people_beats(line: str, facts: _Facts, siblings: Sequence[str]) -> list[str]:
    """What sets this frame's people apart from the other frames of its moment."""
    if not facts.names or not siblings:
        return []
    own = set(facts.names)
    theirs = [set(_read(s).names) for s in siblings]
    sharing = [s for s, names in zip(siblings, theirs, strict=True) if own <= names]
    if not sharing:
        if not any(theirs):
            return ["the only one with a person"]
        if len(own) == 1:
            return [f"the only one with {facts.names[0]}"]
        return ["the only one with both" if len(own) == 2 else f"the only one with all {len(own)}"]
    rung = framing_visibility(line).rung
    if rung and rung > max(framing_visibility(s).rung for s in sharing):
        return [f"the clearest view of {_who(facts.names)}"]
    return []


def _beats(
    line: str,
    facts: _Facts,
    *,
    kind: str,
    starred: bool,
    kept_by_owner: bool,
    siblings: Sequence[str],
) -> list[str]:
    beats = [
        "kept by the owner" if kept_by_owner else "",
        "starred" if starred else "",
        _motion(facts, kind),
        *_people_beats(line, facts, siblings),
    ]
    if siblings and _SOFT not in line and any(_SOFT in s for s in siblings):
        beats.append(f"the sharpest of {len(siblings) + 1}")
    return [beat for beat in beats if beat][:_MAX_BEATS]


def _noun(facts: _Facts, kind: str) -> str:
    motion = _motion(facts, kind)
    return f"a {motion}" if motion else "a photo"


def _cut(text: str, room: int) -> str:
    if len(text) <= room:
        return text
    return text[: max(room - 1, 0)].rsplit(" ", 1)[0].rstrip(" ,;") + "…"


def _head(facts: _Facts, place: str, room: int) -> str:
    who = _who(facts.names)
    if not facts.caption:
        return f"{who} at {place}" if who and place else who or place
    room -= len(who) + len(SEPARATOR) if who else 0
    what = facts.caption
    if place and place.casefold() not in what.casefold() and len(what) + len(place) + 2 <= room:
        what += f", {place}"
    return SEPARATOR.join(part for part in (who, _cut(what, room)) if part)


def shot_reason(
    line: str,
    *,
    kind: str = "still",
    starred: bool = False,
    kept_by_owner: bool = False,
    story_title: str = "",
    siblings: Sequence[str] = (),
) -> str:
    """Why this shot is in the cut, at most `REASON_CHARS` characters, from its own facts.

    `line` is the shot's annotation line, `kind` the carrier's kind (`video`, `live-motion`,
    `still`...), `siblings` the lines of the other pictures of its moment it was chosen over.
    """
    facts = _read(line)
    named = (
        len(story_title) <= _STORY_NAME_CHARS and facts.place.casefold() in story_title.casefold()
    )
    place = "" if named else facts.place
    beats = _beats(
        line, facts, kind=kind, starred=starred, kept_by_owner=kept_by_owner, siblings=siblings
    )
    tail = "".join(SEPARATOR + beat for beat in beats)
    head = _head(facts, place, REASON_CHARS - len(tail))
    if not head:
        motion = _motion(facts, kind)
        head = _noun(facts, kind)
        beats = [beat for beat in beats if beat != motion]
        tail = "".join(SEPARATOR + beat for beat in beats)
    return head + tail


def shot_reason_of_row(
    row: Mapping[str, Any], *, story_title: str = "", siblings: Sequence[str] = ()
) -> str:
    """`shot_reason` over a carrier row: its line, kind, star and whether the owner required it."""
    return shot_reason(
        str(row.get("line") or ""),
        kind=str(row.get("kind") or "still"),
        starred=bool(row.get("favourite")),
        kept_by_owner=bool(row.get("owner_required")),
        story_title=story_title,
        siblings=siblings,
    )
