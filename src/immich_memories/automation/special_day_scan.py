"""Scanning a library for days worth resurfacing.

Lives here rather than in a script because it is meant to run on a schedule:
the point of the catalogue is a memory nobody asked for — five years to the
day since the wedding, ten since the race — and that needs the days found in
advance, not while a video is waiting to render.

What it skips matters as much as what it finds. A holiday already has its own
memory, and every day inside a trip clears the structural bar here without
being remarkable on its own.
"""

from __future__ import annotations

import collections
import copy
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from immich_memories.analysis.picture_copies import picture_copies, starred_keepers
from immich_memories.analysis.special_day import (
    SpecialDay,
    active_hours,
    ask_if_special,
    candidate_days,
    days_covered_by_trips,
    event_window,
    pictures_inside,
    run_extent,
    window_that_holds_the_day,
)
from immich_memories.analysis.special_day_holiday import holiday_name, was_the_holiday
from immich_memories.analysis.special_day_sequence import (
    MIN_FILM_SECONDS,
    filmable_seconds,
    read_in_sequence,
)
from immich_memories.analysis.special_day_title import honest_title
from immich_memories.analysis.special_day_vocabulary import crowded_out, distinctive_days, telling
from immich_memories.analysis.special_event_scope import SpecialEventAdmission
from immich_memories.analysis.trip_detection import detect_trips, haversine_km
from immich_memories.automation.special_day_facts import ranked_occasions
from immich_memories.config_models_analysis import AnalysisConfig
from immich_memories.config_models_automation import TripsConfig
from immich_memories.config_models_render import PhotoConfig
from immich_memories.memory_types.date_builders import KNOWN_HOLIDAYS, resolve_holiday

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from immich_memories.db import Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredDay:
    """What the scan made of one candidate day.

    Usually a day worth a memory of its own. With `judged` false it is a day
    the scan reached and could not read: the catalogue records those so a
    later run knows they were not simply missed, and no reader offers them.
    """

    day: date
    title: str
    subtitle: str
    what: str
    photos: int
    window: tuple[datetime, datetime] | None
    # How long the day stayed awake, and when it did. The run is keyed by the
    # date it began and can end on another one, so its extent is the only
    # honest scope for a memory of it — the calendar day stops at midnight.
    active_hours: int = 0
    run_start: datetime | None = None
    run_end: datetime | None = None
    event_id: str | None = None
    asset_ids: tuple[str, ...] = ()
    event_admission: SpecialEventAdmission | None = None
    judged: bool = True
    unjudged_because: str = ""
    # How many of the day's pictures the recorded window holds, against `photos`.
    # Zero means a scan from before #1067 that never counted, so its window is
    # taken as written; every other row can be checked without re-fetching the
    # day. With no window the whole day is the scope, so this equals `photos`.
    window_photos: int = 0
    # Which scan produced this. Empty means a scan from before #1065, which
    # stamped nothing and asked a question a pleasant afternoon answered yes to.
    prompt_version: str = ""
    app_version: str = ""


def holidays_in(year: int, extra: Iterable[str] = (), *, country: str = "US") -> dict[date, str]:
    """Dates a holiday memory already covers, each with the holiday's name.

    Nothing is defined here: date_builders owns which holidays exist and when
    they fall, moving ones included. Adding one there is enough for it to be
    skipped here too.
    """
    covered: dict[date, str] = {}
    for name in (*KNOWN_HOLIDAYS, *extra):
        try:
            covered[resolve_holiday(name, year, country=country)] = holiday_name(name)
        except ValueError:
            logger.debug("Not a holiday this build knows: %r", name)
    return covered


def _one_file_per_picture(assets: list) -> list:
    """Each picture once, from its full-size file, with a star any of its files carries.

    A shared album stores a curated picture twice, the camera's file and a smaller copy under
    the same name at the same instant, and discovery counted both: a day looked twice its size.
    The fold is the editor's own (`picture_copies`); a file with no name is never folded.
    """
    named = [asset for asset in assets if getattr(asset, "original_file_name", None)]
    copies = picture_copies(named)
    if not copies:
        return assets
    starred = starred_keepers(copies, named)
    logger.info(
        "%d of %d files are other files of a picture; each counts once", len(copies), len(assets)
    )
    return [
        _with_star(asset) if asset.id in starred else asset
        for asset in assets
        if asset.id not in copies
    ]


def _with_star(asset: Any) -> Any:
    starred = copy.copy(asset)
    starred.is_favorite = True
    return starred


def _shot_here(assets: list, analysis_config: Any) -> tuple[list, list]:
    """Whatever of this year the library's own camera made, and the pictures forwarded to it.

    Forwarded pictures (sent by someone else, or saved) are what a messaging app or a race's
    photographers left behind. They are evidence of a day the camera already made, never a day
    of their own: their time is when they were saved, and a film cannot use them. Screen
    recordings and the other excluded sources are neither.
    """
    from immich_memories.analysis.source_filter import from_an_excluded_source, not_shot_here

    if analysis_config is None:
        return assets, []
    patterns = getattr(analysis_config, "exclude_filename_patterns", ())
    stills_need_a_camera = getattr(analysis_config, "exclude_stills_without_camera_exif", False)
    kept: list = []
    forwarded: list = []
    for asset in assets:
        if not not_shot_here(asset, patterns=patterns, stills_need_a_camera=stills_need_a_camera):
            kept.append(asset)
        elif not from_an_excluded_source(getattr(asset, "original_file_name", None), patterns):
            forwarded.append(asset)
    if len(kept) < len(assets):
        logger.info(
            "Source filter: %d of %d assets were not shot here; %d forwarded kept as evidence",
            len(assets) - len(kept),
            len(assets),
            len(forwarded),
        )
    return kept, forwarded


# Three or more files stamped with one exact second were saved together: the stamp is when they
# were saved, not when anything happened (measured: 0.9% of camera photos, 26% of stripped ones).
_ONE_SAVE = 3
# How many sent pictures a day that stands out is judged with.
_TOLD = 3


def _kept_away_from_home(items: list, home: tuple[float, float], min_km: float) -> bool:
    """Did the day's located pictures happen somewhere other than home?

    The holiday memory covers the holiday as it is actually kept — at home,
    with the people who keep it. A day that merely falls on the same date and
    was spent 67 km away at a race circuit is not that holiday, and dropping
    it on the date alone lost a day that would have ranked third in its year.

    No coordinates at all is not evidence against the holiday, so those days
    stay skipped exactly as before.
    """
    away = at_home = 0
    for asset in items:
        exif = getattr(asset, "exif_info", None)
        lat = getattr(exif, "latitude", None) if exif else None
        lon = getattr(exif, "longitude", None) if exif else None
        if lat is None or lon is None:
            continue
        if haversine_km(lat, lon, *home) >= min_km:
            away += 1
        else:
            at_home += 1
    return away > at_home


def _drop_the_holidays_it_actually_was(
    candidates: dict[date, list],
    holidays: set[date],
    home: tuple[float, float] | None,
    min_km: float,
) -> dict[date, list]:
    """Keep the days whose evidence disagrees with the holiday they fall on."""
    kept: dict[date, list] = {}
    for day, items in candidates.items():
        if day not in holidays:
            kept[day] = items
        elif home and _kept_away_from_home(items, home, min_km):
            logger.info("%s falls on a holiday but was spent away from home; keeping it", day)
            kept[day] = items
        else:
            logger.info("Skipping %s: a holiday, and the day never left home", day)
    return kept


def scan_year(
    assets: list,
    *,
    llm_config: Any,
    home: tuple[float, float] | None,
    extra_holidays: Iterable[str] = (),
    analysis_config: Any = None,
    trips_config: TripsConfig | None = None,
    captions: dict[str, str] | None = None,
    judgments: Store | None = None,
    still_seconds: float | None = None,
    reader: Literal["model", "rules"] = "model",
    close_family: Mapping[str, str] | None = None,
    per_year: int = 6,
    country: str = "US",
) -> list[DiscoveredDay]:
    """Find the days in one year's assets that were occasions, and name them.

    Every run of activity off a trip is read, a month at a time and in order, and the reader
    says which were occasions (`special_day_sequence`); no bar decides what it may see. Each
    occasion a film could be cut from is then confirmed and named from its own pictures' lines.
    A negative day-level verdict drops it, even when the month proposed it. A month the
    reader could not read raises `YearNotRead` so the year is scanned again, not recorded
    half-read; the months it did read are banked and cost nothing the second time.

    With `reader="rules"` (no model configured) nothing is asked at all: a run is an
    occasion when one of its recorded facts is loud (`_occasion_by_facts`), and it is
    titled from its own place. The film floor applies the same on both tiers.
    `close_family` maps Immich person ids to close family roles (`close_family_roles`). The
    no-model tier keeps only the `per_year` strongest (`special_day_facts`); the model tier
    keeps every occasion the day-level reading confirms.

    Anything generation would throw away is removed first, so the scan judges
    the same library a memory could actually be cut from. Measured on a real
    day the scan called special: 37 of its 223 assets were received or
    downloaded rather than shot, and they counted toward the day's volume and
    its active hours and could be sampled into the prompt — so the model
    narrated pictures nobody in the library had taken. Forwarded pictures come
    back only as marked evidence of a day the camera made: an obstacle race
    whose 123 pictures were saved from its photographers read, on the owner's
    25 alone, as a jog on a path.
    """
    if not assets:
        return []

    assets = _one_file_per_picture(assets)
    assets, forwarded = _shot_here(assets, analysis_config)
    if not assets:
        return []

    trips = trips_config or TripsConfig()
    year = assets[0].file_created_at.year
    # Dates only: the trip's name is never read here, and asking for one
    # is a live request per trip for every year of the scan.
    away = (
        days_covered_by_trips(
            detect_trips(
                assets,
                *home,
                min_distance_km=trips.min_distance_km,
                min_duration_days=trips.min_duration_days,
                max_gap_days=trips.max_gap_days,
                name_locations=False,
            )
        )
        if home
        else set()
    )
    holidays = holidays_in(year, extra_holidays, country=country)

    off_trip = candidate_days(assets, away_days=away)
    candidates = _drop_the_holidays_it_actually_was(
        off_trip, set(holidays), home, trips.min_distance_km
    )
    forwarded_on = _by_day(forwarded, candidates)
    words = _standing_out(assets, captions, candidates, forwarded_on, reader)
    occasions = _occasions(
        candidates,
        year=year,
        reader=reader,
        home=home,
        away_km=trips.min_distance_km,
        captions=captions,
        llm_config=llm_config,
        judgments=judgments,
        family=close_family or {},
        standing_out=words.standing,
        held=_held_holidays(off_trip, candidates, holidays),
    )
    logger.info(
        "%d: %d occasions, %d dates covered by trips, %d dropped as the holiday they fell on",
        year,
        len(occasions),
        len(away),
        len(off_trip) - len(candidates),
    )

    clip_seconds = (analysis_config or AnalysisConfig()).optimal_clip_duration
    stills = PhotoConfig().duration if still_seconds is None else still_seconds
    # The no-model tier walks its occasions strongest first and stops at the year's few; the
    # model tier names every one it read.
    limit = per_year if reader == "rules" else len(occasions)
    judge = _Judge(
        reader=reader,
        llm_config=llm_config,
        captions=captions,
        judgments=judgments,
        told=words.told,
        holidays=holidays,
        read_as_candidates=set(candidates),
        stills=stills,
        clip_seconds=clip_seconds,
    )
    found: list[DiscoveredDay] = []
    for day, what in occasions.items():
        if len(found) >= limit:
            break
        if (outcome := judge.day(day, off_trip[day], what)) is not None:
            found.append(outcome)
    return sorted(_thinned(found, words), key=lambda entry: entry.day)


def _occasions(
    candidates: dict[date, list],
    *,
    year: int,
    reader: str,
    home: tuple[float, float] | None,
    away_km: float,
    captions: dict[str, str] | None,
    llm_config: Any,
    judgments: Store | None,
    family: Mapping[str, str],
    standing_out: Mapping[date, str],
    held: Mapping[date, str],
) -> dict[date, str]:
    """The occasions among these runs and what each was: read by the model, or by the facts."""
    if reader == "rules":
        return ranked_occasions(candidates, home=home, away_km=away_km, family=family)
    reading = read_in_sequence(
        candidates, captions=captions, llm_config=llm_config, judgments=judgments, family=family
    )
    logger.info(
        "%d: %d runs read, %d with nothing recorded beyond the clock",
        year,
        reading.offered,
        reading.silent,
    )
    if reading.unread_months:
        raise YearNotRead(year, reading.unread_months)
    # The month reading compares a month's days and misses some; what a day's own words make
    # stand out from its year goes to the same day check.
    added = {day: f"a day of {words}" for day, words in standing_out.items()}
    added = {day: what for day, what in added.items() if day not in reading.found}
    logger.info("%d: %d more days stand out by their words", year, len(added))
    # A holiday spent at home is judged like any day, then asked whether it was the holiday.
    return dict(sorted((dict(held) | reading.found | added).items()))


def _standing_out(
    assets: list,
    captions: Mapping[str, str] | None,
    candidates: Mapping[date, list],
    forwarded_on: Mapping[date, list],
    reader: str,
) -> _Words:
    """The candidate days whose own words, and half of what was sent from them, stand out, and
    what of the sent pictures each will be judged with.

    Only a day that stands out hears what was sent from it, and only the pictures that say
    most of what the year does not: a day the month reading proposed is judged on its own.
    """
    if reader == "rules" or not captions:
        return _Words({}, {}, {})
    said = _said_by_day(assets, captions)
    standing = distinctive_days(
        said,
        candidates,
        forwarded={day: _said(sent, captions) for day, sent in forwarded_on.items()},
    )
    told = {day: telling(forwarded_on.get(day, []), captions, said, keep=_TOLD) for day in standing}
    return _Words(standing, told, said)


class _Words(NamedTuple):
    standing: dict[date, str]
    told: dict[date, list]
    said: dict[date, list[str]]


def _held_holidays(
    off_trip: Mapping[date, list], candidates: Mapping[date, list], holidays: Mapping[date, str]
) -> dict[date, str]:
    """The holidays spent at home, proposed to the day check under their own name."""
    return {
        day: f"a day that fell on {name}"
        for day, name in holidays.items()
        if day in off_trip and day not in candidates
    }


def _thinned(found: list[DiscoveredDay], words: _Words) -> list[DiscoveredDay]:
    """The confirmed days, less those that only repeat the crowd of confirmed days around them."""
    crowd = crowded_out([entry.day for entry in found], words.said, exempt=words.standing)
    if crowd:
        logger.info(
            "%d confirmed days only repeat the days around them: %s",
            len(crowd),
            ", ".join(str(day) for day in sorted(crowd)),
        )
    return [entry for entry in found if entry.day not in crowd]


@dataclass(frozen=True)
class _Judge:
    """Everything the scan needs to judge one proposed day."""

    reader: str
    llm_config: Any
    captions: Mapping[str, str] | None
    judgments: Store | None
    told: Mapping[date, list]
    holidays: Mapping[date, str]
    read_as_candidates: set[date]
    stills: float
    clip_seconds: float

    def day(self, day: date, items: list, what: str) -> DiscoveredDay | None:
        """The day's row, or None when it cannot be filmed, is not an occasion, or was the
        holiday it fell on."""
        if filmable_seconds(items, still_seconds=self.stills, clip_seconds=self.clip_seconds) < (
            MIN_FILM_SECONDS
        ):
            logger.info("%s read as %r, dropped for want of material to film", day, what)
            return None
        if self.reader == "rules":
            verdict = SpecialDay(
                special=True, title=honest_title(items, what=what, evidence=""), what=what
            )
        else:
            verdict = _read_the_day(
                items, self.llm_config, self.captions, self.judgments, self.told.get(day, [])
            )
        if verdict.special and self._was_the_holiday(day, verdict):
            return None
        return _day_from(day, items, verdict, what)

    def _was_the_holiday(self, day: date, verdict: SpecialDay) -> bool:
        if self.reader == "rules" or day not in self.holidays:
            return False
        holiday = self.holidays[day]
        answer = was_the_holiday(
            holiday, verdict.title, verdict.what, self.llm_config, self.judgments
        )
        # No answer keeps what the scan did before: a holiday at home is its holiday's.
        the_holiday = answer if answer is not None else day not in self.read_as_candidates
        if the_holiday:
            logger.info("%s was %s itself; the holiday's own memory has it", day, holiday)
        return the_holiday


def _said(pictures: list, captions: Mapping[str, str]) -> list[str]:
    return [captions[a.id] for a in pictures if captions.get(a.id)]


def _said_by_day(assets: list, captions: Mapping[str, str]) -> dict[date, list[str]]:
    """What was written about each day's own pictures, for the year they stand out from."""
    said: dict[date, list[str]] = collections.defaultdict(list)
    for asset in assets:
        if text := captions.get(asset.id):
            said[asset.file_created_at.date()].append(text)
    return said.copy()


def _by_day(forwarded: list, candidates: Mapping[date, list]) -> dict[date, list]:
    """The forwarded pictures each candidate day can be said to hold.

    A day of forwards alone is not a candidate. A batch saved in one second is dated by the save,
    so it counts only inside the day's own run, while the camera was out too: on a race day 47
    of 58 such pictures were the race's own photographs; over its year, 118 of 243 counted.
    """
    second = collections.Counter(a.file_created_at.replace(microsecond=0) for a in forwarded)
    runs = {day: run_extent(items) for day, items in candidates.items()}
    on: dict[date, list] = collections.defaultdict(list)
    for asset in forwarded:
        day = asset.file_created_at.date()
        if day in runs and (
            second[asset.file_created_at.replace(microsecond=0)] < _ONE_SAVE
            or _during(asset, runs[day])
        ):
            on[day].append(asset)
    return on.copy()


def _during(asset: Any, run: tuple[datetime, datetime] | None) -> bool:
    return run is not None and run[0] <= asset.file_created_at <= run[1]


class YearNotRead(RuntimeError):
    """Some months of a year could not be read; the year is scanned again rather than kept."""

    def __init__(self, year: int, months: list[str]) -> None:
        super().__init__(f"{year}: {len(months)} month(s) could not be read ({', '.join(months)})")


def _read_the_day(
    items: list,
    llm_config: Any,
    captions: Mapping[str, str] | None,
    judgments: Store | None,
    forwarded: list,
) -> SpecialDay:
    """The day-level verdict, asked once more about the day's event when the day read ordinary.

    Some days contain an occasion rather than being one: a race day began with the cat at
    home and ended there, and the small reader, shown the whole day, named it after the cat.
    Where the pictures were taken already says which stretch the day was spent on
    (`event_window`), so an ordinary verdict is asked again about that stretch alone. A day
    with no such stretch, or one the reader already called an occasion, is asked once.
    """

    def ask(pictures: list) -> SpecialDay:
        return ask_if_special(
            pictures,
            llm_config,
            captions={
                a.id: captions[a.id]
                for a in [*pictures, *forwarded]
                if captions and captions.get(a.id)
            },
            judgments=judgments,
            forwarded=forwarded,
        )

    verdict = ask(items)
    if verdict.special or not verdict.judged:
        return verdict
    window = window_that_holds_the_day(event_window(items), items)
    if window is None:
        return verdict
    start, end = window
    logger.info(
        "%s read as ordinary; asking about its %s-%s stretch at one place",
        items[0].file_created_at.date(),
        f"{start:%H:%M}",
        f"{end:%H:%M}",
    )
    inside = ask([a for a in items if start <= a.file_created_at <= end])
    return inside if inside.special else verdict


def _day_from(day: date, items: list, verdict: Any, what: str = "") -> DiscoveredDay | None:
    """One candidate day's row, or nothing when there is nothing honest to write.

    A title, not just something written about the day. Every reader of the
    catalogue falls back to `what` when the title is empty, so an entry with no
    title is how the day's own description — "Six images captured between 07:32
    and 16:06, tracing a route from weathered apar" — ended up on a card. The
    ask already offers the day's place or its `what` where either can carry a
    title; nothing left after that means nothing truthful to call the day.
    """
    from immich_memories import __version__
    from immich_memories.analysis.special_day_sequence import SCAN_VERSION

    started, ended = run_extent(items) or (None, None)
    if not verdict.judged:
        return DiscoveredDay(
            day=day,
            title="",
            subtitle="",
            what="",
            photos=len(items),
            window=None,
            judged=False,
            unjudged_because=verdict.unjudged_because,
            prompt_version=SCAN_VERSION,
            app_version=__version__,
        )
    # The month proposes an occasion; its own evidence must independently confirm it.
    if not verdict.special or not verdict.title:
        return None
    # The model read the day's own timestamps and what the lines said was in
    # the frames; event_window only knows where the pictures were. Either way
    # the window has to hold the day before it is written down.
    window = window_that_holds_the_day(verdict.window or event_window(items), items)
    return DiscoveredDay(
        day=day,
        title=verdict.title,
        subtitle=verdict.subtitle,
        what=verdict.what or what,
        photos=len(items),
        window=window,
        active_hours=active_hours(items),
        run_start=started,
        run_end=ended,
        window_photos=pictures_inside(window, items),
        prompt_version=SCAN_VERSION,
        app_version=__version__,
    )


def same_day_in(day: date, year: int) -> date:
    """The same calendar day in another year; 29 February falls back to the 28th."""
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


def anniversaries_due(
    catalogue: Iterable[DiscoveredDay],
    on: date,
    *,
    window_days: int = 3,
) -> list[tuple[DiscoveredDay, int]]:
    """Discovered days whose anniversary falls near a date, roundest first.

    Ten years reads louder than nine, which is the whole appeal of arriving
    unannounced.

    The candidate is looked for in the years either side of the check as well
    as its own. A day at the end of December has its anniversary a few days
    before a check in early January, and trying only the check's own year put
    that candidate 364 days away — while counting the years to the calendar
    year rather than to the anniversary itself, which read eleven years for a
    tenth.
    """
    due: list[tuple[DiscoveredDay, int]] = []
    for entry in catalogue:
        for year in (on.year - 1, on.year, on.year + 1):
            years = year - entry.day.year
            if years < 1:
                continue
            if abs((same_day_in(entry.day, year) - on).days) <= window_days:
                due.append((entry, years))
                break
    return sorted(
        due, key=lambda pair: (0 if pair[1] % 10 == 0 else 1 if pair[1] % 5 == 0 else 2, -pair[1])
    )
