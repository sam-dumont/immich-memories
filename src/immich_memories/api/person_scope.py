"""Which pictures a memory's people imply, whichever surface asked.

Naming nobody takes the window whole. Naming people reads the window whole too, once,
and keeps every picture of an episode the people are in (`analysis/person_presence.py`):
a face recognised once in an afternoon puts that person in all of it. Several people are
an intersection (``and``: everybody recognised somewhere in the episode) or a union
(``or``: anybody). Both the CLI and wizard ask through here so the choice is made before
Cull, and the pool the owner reviews already holds those pictures.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal, Protocol

from immich_memories.analysis.person_presence import (
    episodes_of,
    people_condition,
    present_in_episodes,
)
from immich_memories.api.person_expression import PersonExpression

if TYPE_CHECKING:
    from immich_memories.timeperiod import DateRange


class VideoSource(Protocol):
    """The unfiltered video read of one window."""

    def get_videos_for_date_range(self, date_range: DateRange) -> list: ...


class PhotoSource(Protocol):
    """The photo endpoint a windowed fetch can reach."""

    def get_photos_for_date_range(
        self,
        date_range: DateRange,
        progress_callback: Callable[[int, int], None] | None = None,
        person_id: str | None = None,
        person_ids: list[str] | None = None,
    ) -> Sequence[Any]: ...


class WindowSource(VideoSource, PhotoSource, Protocol):
    """Both reads, which episode presence needs: an episode mixes videos and photos."""


PersonMatch = Literal["and", "or"]


def _person_match(value: str) -> PersonMatch:
    if value == "and":
        return "and"
    if value == "or":
        return "or"
    raise ValueError(f"person_match must be 'and' or 'or', got {value!r}")


def window_condition(
    person_ids: list[str],
    *,
    person_match: str = "and",
    person_expression: PersonExpression | None = None,
) -> PersonExpression | None:
    """The fetch's people as one condition over face IDs, or None when it names nobody."""
    match = _person_match(person_match)
    if person_expression is not None and person_ids:
        raise ValueError("person_expression cannot be combined with nonempty person_ids")
    return people_condition(person_ids, match, person_expression)


def people_in_window(
    client: WindowSource, date_range: DateRange, condition: PersonExpression
) -> tuple[list, list]:
    """The videos and photos of one window whose episode holds ``condition`` (face IDs).

    Two reads per window whatever the number of people: per-person queries answer per
    frame, which is the question this replaces.
    """
    videos = client.get_videos_for_date_range(date_range)
    photos = list(client.get_photos_for_date_range(date_range))
    present = present_in_episodes(episodes_of([*videos, *photos]), condition)
    return _in_order(videos, present), _in_order(photos, present)


def _in_order(assets: Sequence[Any], present: frozenset[str]) -> list:
    return sorted(
        (asset for asset in assets if asset.id in present),
        key=lambda asset: (asset.file_created_at, asset.id),
    )


def videos_in_window(
    client: WindowSource,
    person_ids: list[str],
    date_range: DateRange,
    *,
    person_match: str = "and",
    person_expression: PersonExpression | None = None,
) -> list:
    """The videos one window holds, narrowed to the episodes of the people it names."""
    condition = window_condition(
        person_ids, person_match=person_match, person_expression=person_expression
    )
    if condition is None:
        return client.get_videos_for_date_range(date_range)
    return people_in_window(client, date_range, condition)[0]


def photos_in_window(
    client: WindowSource,
    person_ids: list[str],
    date_range: DateRange,
    *,
    person_match: str = "and",
    person_expression: PersonExpression | None = None,
) -> list:
    """The photos one window holds, with the same episode rule as videos."""
    condition = window_condition(
        person_ids, person_match=person_match, person_expression=person_expression
    )
    if condition is None:
        return list(client.get_photos_for_date_range(date_range))
    return people_in_window(client, date_range, condition)[1]
