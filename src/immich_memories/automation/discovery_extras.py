"""The reads behind the season, holiday, album, backfill and per-person month detectors.

Each one is scoped to what a detector has already decided is due, and none of them may end
discovery: a server that cannot answer one of these questions costs that detector its
candidate, with the reason in `auto suggest`, not the nightly run.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from typing import Any, TypeVar

from immich_memories.automation.calendar_detectors import birthday_film_windows
from immich_memories.automation.material import (
    Window,
    days_in,
    person_days_in,
    pictures_in,
)
from immich_memories.automation.season_holiday_detectors import HolidayDetector, SeasonDetector
from immich_memories.config_models_automation import AutomationConfig
from immich_memories.timeperiod import DateRange

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# A birthday under this many pictures is dropped without asking how many days they span.
_BIRTHDAY_MIN_PICTURES = 50


@dataclass(frozen=True)
class ExtraPlan:
    """What discovery knows before it reads: the questions the detectors may ask."""

    auto_cfg: AutomationConfig
    today: date
    hemisphere: str | None
    country: str | None
    generated_keys: Collection[str]
    # Account, local person id -> canonical id, as the people store binds them.
    canon: Mapping[tuple[str, str], str]
    # Every Immich person id the registry calls close, under any account.
    close_ids: Collection[str]
    birth_dates: Callable[[str, list], dict[str, date]]


@dataclass
class ExtraReads:
    """What the new detectors consume, merged over every account read."""

    albums: list[dict[str, Any]] = field(default_factory=list)
    user_id: str | None = None
    season_days: dict[Window, dict[date, int]] = field(default_factory=dict)
    holiday_pictures: dict[Window, int] = field(default_factory=dict)
    person_days: dict[str, dict[date, int]] = field(default_factory=dict)
    birthday_days: dict[str, set[date]] = field(default_factory=dict)
    closeness: dict[str, float] = field(default_factory=dict)
    close_ids: Collection[str] = ()
    country: str | None = None
    notes: list[str] = field(default_factory=list)


def read_account_extras(
    client: Any,
    account: str,
    user_id: str | None,
    people: list,
    birthday_counts: Mapping[str, int],
    plan: ExtraPlan,
    primary: bool,
    into: ExtraReads,
) -> None:
    """Add one account's answers to ``into``; a failed read adds a note instead."""
    cfg = plan.auto_cfg
    if cfg.detect_seasons:
        due = SeasonDetector().due(plan.today, plan.hemisphere, plan.generated_keys)
        if due is not None:
            counted = _guard(
                "the season's pictures", lambda: days_in([client], due.window), into.notes
            )
            _sum_days(into.season_days.setdefault(due.window, {}), counted or {})
    if cfg.detect_holidays:
        _read_holidays(client, plan, into)
    if cfg.detect_albums and primary:
        albums = _guard("the albums", partial(_albums_of, client), into.notes)
        into.albums, into.user_id = albums or [], user_id
    if cfg.detect_person_monthly:
        _read_person_months(client, account, people, plan, into)
    _read_birthday_days(client, account, people, birthday_counts, plan, into)


def _read_holidays(client: Any, plan: ExtraPlan, into: ExtraReads) -> None:
    for due in HolidayDetector().due(
        plan.today, plan.country, plan.auto_cfg.extra_holidays, plan.generated_keys
    ):
        for window in due.windows:
            counted = _guard(
                "a holiday's pictures", partial(pictures_in, [client], window), into.notes
            )
            into.holiday_pictures[window] = into.holiday_pictures.get(window, 0) + (counted or 0)


def _read_person_months(
    client: Any, account: str, people: list, plan: ExtraPlan, into: ExtraReads
) -> None:
    window = _person_window(plan.today)
    for person in people:
        if not person.name or person.id not in plan.close_ids:
            continue
        canonical = plan.canon.get((account, person.id), person.id)
        counted = _guard(
            "a close person's pictures",
            partial(person_days_in, [(client, person.id)], window),
            into.notes,
        )
        _sum_days(into.person_days.setdefault(canonical, {}), counted or {})


def _read_birthday_days(
    client: Any,
    account: str,
    people: list,
    birthday_counts: Mapping[str, int],
    plan: ExtraPlan,
    into: ExtraReads,
) -> None:
    """The days a birthday film's pictures were taken on, for the ones that have enough."""
    births = plan.birth_dates(account, people)
    for person in people:
        windows = (
            birthday_film_windows(births[person.id], plan.today) if person.id in births else None
        )
        if not windows or birthday_counts.get(person.id, 0) < _BIRTHDAY_MIN_PICTURES:
            continue
        canonical = plan.canon.get((account, person.id), person.id)
        for window in windows:
            counted = _guard(
                "a birthday's pictures",
                partial(_person_days_in_range, client, person.id, window),
                into.notes,
            )
            if counted:
                # No answer is not zero days: the detector then judges on pictures alone.
                into.birthday_days.setdefault(canonical, set()).update(counted)


def _albums_of(client: Any) -> list[dict[str, Any]]:
    return client.get_albums()


def _person_days_in_range(client: Any, person_id: str, window: DateRange) -> dict[date, int]:
    return person_days_in([(client, person_id)], (window.start.date(), window.end.date()))


def _person_window(today: date) -> Window:
    """From the first of the month three completed months back to the end of the last one."""
    year, month = today.year, today.month
    for _ in range(3):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return date(year, month, 1), date(today.year, today.month, 1) - date.resolution


def _sum_days(into: dict[date, int], more: Mapping[date, int]) -> None:
    counted = Counter(into)
    counted.update(more)
    into.clear()
    into.update(counted)


def _guard(what: str, read: Callable[[], _T], notes: list[str]) -> _T | None:
    try:
        return read()
    except Exception as exc:  # WHY: one unanswered question must not end the nightly run
        logger.warning("Could not read %s: %s", what, exc)
        notes.append(
            f"Could not read {what} from Immich ({type(exc).__name__}); that detector skipped"
        )
        return None
