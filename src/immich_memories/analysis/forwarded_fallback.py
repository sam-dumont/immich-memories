"""Forwarded copies fill the gaps in a film's camera timeline (opt-in).

Every film refuses a picture nobody's camera took: a messaging export or a saved image
(`source_quality.FORWARDED_COPY`). A year in lockdown, or a birthday's earlier years, can hold
nothing else, and the film then shows none of them. With `analysis.forwarded_copies_when_short`
on, a copy may stand in where the film's camera timeline has a gap, and only there.

The timeline is cut the way the film already cuts time (`gap_units`): each occurrence of a film
of several (a holiday's years, a birthday's earlier birthdays), else the weeks of a film up to two
months long, the months of one up to two years long, the years of a longer one. A unit holding no
camera picture of the film's material is a gap. A gap takes about the share of the film a unit
with camera pictures gets: as many days of copies as such a unit holds days of camera pictures
(the median), the days with most copies first. How short the film is of its length decides
nothing: a person spotlight asks for ten minutes, and every copy would have filled it.

A copy that would stand in is still refused when it is no picture of this life (a collage,
`forwarded_copy_checks`) or a copy of a picture the library already holds, wherever in time that
picture sits: in one of Immich's own duplicate groups with another file, or within the duplicate
review's hash distance of a picture of the film's material that is no copy. A copy carries the
date it was received, so a re-shared old photo with no original in the library can still land in
the wrong year; that is why the setting is off by default.

Admission lets exactly these copies through (`SourceScope.forwarded_stand_ins`); every later check
(standing, the family-viewing check, the duplicate review, the people condition) reads them like
any picture. A screenshot or a document is refused by name or by its heads, never as a copy.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

from immich_memories.analysis.duplicate_hashing import hamming_distance
from immich_memories.analysis.editorial_final_hash_review import STANDALONE_REPEAT_DISTANCE
from immich_memories.analysis.forwarded_copy_checks import composed_in_words, looks_composed
from immich_memories.analysis.selection_source_validation import camera_roll_refusal
from immich_memories.analysis.source_filter import asset_of
from immich_memories.analysis.source_quality import FORWARDED_COPY
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange

# A film this long or shorter is cut into weeks, up to this into months, beyond into years.
_WEEKS_UP_TO_DAYS = 62
_MONTHS_UP_TO_DAYS = 731


@dataclass(frozen=True)
class CopyChecks:
    """What a copy is checked against before it may stand in; empty checks pass every copy.

    `hash_of` is the duplicate review's preview hash, `preview_of` the preview itself,
    `originals` the film's pictures (copies among them are skipped), and `duplicate_groups`
    reads Immich's own duplicate groups over the whole library, as asset ids, once and only
    when a copy is checked.
    """

    hash_of: Callable[[str], str | None] = lambda _asset: None
    preview_of: Callable[[str], bytes | None] = lambda _asset: None
    originals: Sequence[Any] = ()
    duplicate_groups: Callable[[], Sequence[Sequence[str]]] = tuple


@dataclass(frozen=True)
class StandIns:
    """The copies that may stand in, and why each other copy of a gap was refused."""

    ids: frozenset[str] = frozenset()
    refused: Mapping[str, str] = field(default_factory=dict)


def is_forwarded_copy(source: Any, config: Config) -> bool:
    """Whether the only reason a film refuses `source` is that it is a forwarded copy."""
    return camera_roll_refusal(source, config) == FORWARDED_COPY


def stand_in_copies(
    sources: Iterable[Any],
    config: Config,
    *,
    windows: Sequence[DateRange],
    checks: CopyChecks | None = None,
) -> StandIns:
    """The copies of the film's material that fill the gaps in its camera timeline."""
    if not config.analysis.forwarded_copies_when_short:
        return StandIns()
    camera: set[date] = set()
    copies: dict[date, list[Any]] = defaultdict(list)
    for source in sources:
        refusal = camera_roll_refusal(source, config)
        if refusal is None:
            camera.add(_day(source))
        elif refusal == FORWARDED_COPY:
            copies[_day(source)].append(source)
    units = gap_units(windows)
    held = [sum(first <= day <= last for day in camera) for first, last in units]
    share = max(1, round(median(n for n in held if n))) if any(held) else 1
    review = _Review(checks or CopyChecks(), config)
    for unit, camera_days in zip(units, held, strict=True):
        if not camera_days:
            review.fill(unit, copies, share)
    return StandIns(frozenset(review.kept), review.refused)


def gap_units(windows: Sequence[DateRange]) -> list[tuple[date, date]]:
    """The stretches a gap is read over: each occurrence of a film of several, else the weeks,
    months or years of its one window, by how long it is."""
    spans = [(window.start.date(), window.end.date()) for window in windows]
    if len(spans) != 1:
        return spans
    first, last = spans[0]
    length = (last - first).days + 1
    if length <= _WEEKS_UP_TO_DAYS:
        return _cut(first, last, lambda day: day + timedelta(days=7 - day.weekday()))
    if length <= _MONTHS_UP_TO_DAYS:
        return _cut(first, last, _next_month)
    return _cut(first, last, lambda day: date(day.year + 1, 1, 1))


def _cut(first: date, last: date, next_start: Callable[[date], date]) -> list[tuple[date, date]]:
    units, start = [], first
    while start <= last:
        following = next_start(start)
        units.append((start, min(last, following - timedelta(days=1))))
        start = following
    return units


def _next_month(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1]) + timedelta(1)


def _day(source: Any) -> date:
    return asset_of(source).local_taken_at.date()


class _Review:
    """The copies a gap takes, day by day, each checked before it is kept."""

    def __init__(self, checks: CopyChecks, config: Config) -> None:
        self._checks = checks
        self._config = config
        self.kept: set[str] = set()
        self.refused: dict[str, str] = {}
        self._groups: dict[str, Sequence[str]] | None = None
        self._original_hashes: dict[str, str] | None = None

    def fill(self, unit: tuple[date, date], copies: Mapping[date, list[Any]], share: int) -> None:
        """Keep the copies of the unit's richest days, until the unit holds its share of days."""
        first, last = unit
        days = sorted(
            (day for day in copies if first <= day <= last),
            key=lambda day: (-len(copies[day]), day),
        )
        taken = 0
        for day in days:
            if taken >= share:
                break
            passed = [copy for copy in copies[day] if self._passes(copy)]
            self.kept.update(asset_of(copy).id for copy in passed)
            taken += bool(passed)

    def _passes(self, copy: Any) -> bool:
        asset_id = asset_of(copy).id
        reason = self._composed(asset_id) or self._duplicate(asset_id)
        if reason:
            self.refused[asset_id] = reason
        return not reason

    def _composed(self, asset_id: str) -> str:
        preview = self._checks.preview_of(asset_id)
        if preview and looks_composed(preview):
            return "a collage, made rather than taken"
        return ""

    def _duplicate(self, asset_id: str) -> str:
        """The original this copy repeats, in Immich's duplicate groups or by preview hash."""
        others = [other for other in self._group_of().get(asset_id, ()) if other != asset_id]
        if others:
            return f"a copy of {others[0]}, which the library holds"
        own = self._checks.hash_of(asset_id)
        if own is None:
            return ""
        for original, theirs in self._originals().items():
            if hamming_distance(own, theirs) <= STANDALONE_REPEAT_DISTANCE:
                return f"a copy of {original}, which the library holds"
        return ""

    def _group_of(self) -> dict[str, Sequence[str]]:
        if self._groups is None:
            self._groups = {
                asset: group for group in self._checks.duplicate_groups() for asset in group
            }
        return self._groups

    def _originals(self) -> dict[str, str]:
        if self._original_hashes is None:
            self._original_hashes = {}
            for original in self._checks.originals:
                if is_forwarded_copy(original, self._config):
                    continue
                asset_id = asset_of(original).id
                if (theirs := self._checks.hash_of(asset_id)) is not None:
                    self._original_hashes[asset_id] = theirs
        return self._original_hashes


def refused_in_words(line: str) -> str | None:
    """Why a copy's own line refuses it: its caption says it was made rather than taken."""
    if word := composed_in_words(line):
        return f"a {word}, made rather than taken"
    return None
