"""What a story is called and what it shows, from its facts (no model, #2486).

A story's title used to be every episode title joined with " / ": a trip became forty-five
"posing at <town>" segments and a week at home a list of activity labels. A person names a
story by the one thing it is, so the rules do too, in this order:

- an occasion names itself ("Kit's birthday", "Pat and Lou's visit", `editorial_occasions`);
- a trip is the album the owner made for it, else the farthest place it reached
  ("Trip to Nordkapp"); each leg of it runs from its first place to its last
  ("Copenhagen to Nordkapp");
- a day is its date, at its place when it has one ("Tervuren, Sunday 6 July"); a day out
  that is no trip by the install's own rule is named the same way;
- days at home are their span ("Days at home, 1–4 July").

Activity-classifier labels ("posing", "sport-active") never reach a name: they describe a
frame, not a happening, and are often wrong about it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_label(day: str) -> str:
    """ "2025-07-06" -> "Sunday 6 July"."""
    when = date.fromisoformat(day)
    return f"{_WEEKDAYS[when.weekday()]} {when.day} {_MONTHS[when.month - 1]}"


def span_label(first: str, last: str) -> str:
    """The days a story spans, as a person writes them: "1–4 July", "30 June – 2 July"."""
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    if start == end:
        return f"{start.day} {_MONTHS[start.month - 1]}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {_MONTHS[end.month - 1]}"
    return f"{start.day} {_MONTHS[start.month - 1]} – {end.day} {_MONTHS[end.month - 1]}"


def home_name(days: Sequence[str], places: Sequence[str]) -> tuple[str, str]:
    """A story at home that is no occasion: its day, or its span of days."""
    first, last = min(days), max(days)
    if first == last:
        name = f"{places[0]}, {day_label(first)}" if len(set(places)) == 1 else day_label(first)
        return name, f"A day at home, {day_label(first)}"
    return f"Days at home, {span_label(first, last)}", _across(places, "Ordinary days at home")


def outing_name(days: Sequence[str], places: Sequence[str]) -> tuple[str, str]:
    """A stay away too near or too short to be a trip: where it went, and when."""
    first, last = min(days), max(days)
    named = list(dict.fromkeys(p for p in places if p))
    when = day_label(first) if first == last else span_label(first, last)
    name = f"{named[-1]}, {when}" if named else when
    head = "A day out" if first == last else "Days out"
    return name, _across(places, head) if named else f"{head}, {when}"


def trip_name(*, album: str | None, farthest: str | None) -> str:
    """The trip as a whole: the owner's album for it, else where it reached."""
    if album:
        return album
    return f"Trip to {farthest}" if farthest else "A trip away"


def leg_name(places: Sequence[str], *, trip: str, legs: int) -> str:
    """One leg of a trip, from its first place to its last; a one-leg trip is the trip."""
    named = [p for p in places if p]
    if legs <= 1 or not named:
        return trip
    first, last = named[0], named[-1]
    return first if first == last else f"{first} to {last}"


def trip_purpose(days: Sequence[str], places: Sequence[str]) -> str:
    """ "19 days away, from Copenhagen to Kristiansand by Nordkapp"-style facts."""
    first, last = min(days), max(days)
    count = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    named = list(dict.fromkeys(p for p in places if p))
    head = f"{count} days away" if count > 1 else "A day away"
    if len(named) >= 2:
        return f"{head}, {named[0]} to {named[-1]}"
    return f"{head} in {named[0]}" if named else head


def _across(places: Sequence[str], fallback: str) -> str:
    named = list(dict.fromkeys(p for p in places if p))
    if not named:
        return fallback
    if len(named) <= 3:
        return f"{fallback}: {', '.join(named)}"
    return f"{fallback}: {', '.join(named[:3])} and {len(named) - 3} more places"
