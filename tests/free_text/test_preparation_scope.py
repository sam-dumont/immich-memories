"""#2749: a request's place narrows what `--ask` prepares to the pictures it can keep."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.config.loader import Config
from immich_memories.config.models.resources import ImmichConfig
from immich_memories.db import open_store
from immich_memories.free_text import preparation as prep
from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.pool import Translation
from immich_memories.free_text.preparation_scope import place_filter
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import Subject
from immich_memories.free_text.translate import translate
from tests.free_text.banked import BankedAsker, QuestionAsker

TODAY = date(2026, 9, 1)
HOME = Home(50.0, 4.0, since=None, until=None)
AT_HOME = Household({}, homes=(HOME,))
CAT = "A black cat is sleeping"


def _picture(asset_id: str, n: int, **fields: Any) -> LibraryPicture:
    taken = datetime(2020, 1, 1, 12, tzinfo=UTC) + timedelta(days=n)
    return LibraryPicture(asset_id, taken, "photo", **fields)


def _unprepared() -> LibraryView:
    """Four pictures on the plot, two with no GPS, and twenty far away: none has a caption."""
    pictures = [
        *[_picture(f"home-{n}", n, latitude=50.0005, longitude=4.0) for n in range(4)],
        *[_picture(f"nogps-{n}", 10 + n) for n in range(2)],
        *[_picture(f"away-{n}", 20 + n, latitude=52.0, longitude=5.0) for n in range(20)],
    ]
    return LibraryView(pictures=tuple(pictures), people={}, sharpness_line=None)


READING = {
    "Split the owner's request": {
        "who": [],
        "when": ["along the years"],
        "where": [],
        "what": ["our cat"],
    },
    "Give the date range": {"date_from": None, "date_to": None},
    "one single occasion": {"reason": "banked", "choice": "many occasions"},
    "main subject (subject)? Pick one": {"reason": "banked", "choice": "an animal"},
    "name the main subject itself too": {"reason": "banked", "choices": []},
}


def _link(monkeypatch: pytest.MonkeyPatch, scope: str) -> None:
    # WHY: stands in for the model server's vote on where the request's words point.
    monkeypatch.setattr(
        "immich_memories.free_text.translate.link_where",
        lambda *_args, **_kwargs: WhereLink(scope=scope),
    )


def _ask(lexicon: Lexicon, prepare_window: Any) -> Any:
    return translate(
        "our cat along the years",
        _unprepared(),
        AT_HOME,
        lexicon,
        QuestionAsker(READING),
        today=TODAY,
        prepare_window=prepare_window,
    )


def _preparer(prepared: list[frozenset[str]], *, narrow: bool = True):
    """A `prepare_window` that captions what it is told to, and records which pictures."""
    view = _unprepared()

    def prepare_window(_when, place):
        everything = frozenset(picture.asset_id for picture in view.pictures)
        ids = place(view.pictures) if narrow and place else everything
        prepared.append(ids)
        pictures = tuple(
            replace(picture, caption=CAT) if picture.asset_id in ids else picture
            for picture in view.pictures
        )
        return replace(view, pictures=pictures), {}, {}

    return prepare_window


def test_an_at_home_request_prepares_only_the_pictures_taken_at_home(
    lexicon: Lexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link(monkeypatch, "home_at_time")
    prepared: list[frozenset[str]] = []

    asked = _ask(lexicon, _preparer(prepared))

    # A picture without GPS stays: it is no evidence of elsewhere (the pool's own rule).
    assert prepared == [frozenset({"home-0", "home-1", "home-2", "home-3", "nogps-0", "nogps-1"})]
    assert {p.asset_id for p in asked.pool.pictures} == prepared[0]


def test_the_narrowed_pool_is_the_pool_preparing_everything_would_have_built(
    lexicon: Lexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link(monkeypatch, "home_at_time")

    narrowed = _ask(lexicon, _preparer([]))
    everything = _ask(lexicon, _preparer([], narrow=False))

    assert {p.asset_id for p in narrowed.pool.pictures} == {
        p.asset_id for p in everything.pool.pictures
    }
    assert narrowed.pool.pictures


def test_a_request_with_no_place_prepares_the_whole_window(
    lexicon: Lexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link(monkeypatch, "anywhere")
    placed: list[Any] = []
    view = _unprepared()

    def prepare_window(_when, place):
        placed.append(place)
        return view, {}, {}

    _ask(lexicon, prepare_window)

    assert placed == [None]


def test_a_place_metadata_cannot_settle_keeps_the_whole_window(
    lexicon: Lexicon, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link(monkeypatch, "trips")
    placed: list[Any] = []
    view = _unprepared()

    def prepare_window(_when, place):
        placed.append(place)
        return view, {}, {}

    _ask(lexicon, prepare_window)

    assert placed == [None]


def _house(where: str = "home_at_time", **subject: Any) -> Translation:
    request = "the evolution of our house"
    return Translation(
        Reading(request=request, what=(request,)),
        WhoLink(),
        WhenLink(),
        WhereLink(scope=where),
        LibraryFacts(),
        Subject(heads=("house",), words=("house",), main=("house",), **subject),
    )


def test_one_particular_place_prepares_only_the_pictures_that_carry_gps_at_home(
    lexicon: Lexicon,
) -> None:
    pictures = _unprepared().pictures
    # WHY: stands in for the model server; every answer says the house is a place.
    asker = BankedAsker(*[{"reason": "banked", "choice": "a place"}] * 3)

    one = place_filter(_house(), AT_HOME, lexicon, asker)
    any_of_a_kind = place_filter(_house(kind="an animal"), AT_HOME, lexicon, BankedAsker())

    assert one is not None and any_of_a_kind is not None
    assert one(pictures) == {"home-0", "home-1", "home-2", "home-3"}
    assert any_of_a_kind(pictures) == {f"home-{n}" for n in range(4)} | {"nogps-0", "nogps-1"}


def test_a_named_place_in_the_request_keeps_the_whole_window(lexicon: Lexicon) -> None:
    translation = _house()
    named = replace(translation, facts=LibraryFacts(places=(("city", "Springfield"),)))

    assert place_filter(named, AT_HOME, lexicon, BankedAsker()) is None


def _library_dicts() -> list[dict]:
    from tests.household_fake import PRIMARY_KEY, picture  # noqa: F401

    at_home = picture("p-home", "primary", 1, ())
    at_home["exifInfo"] = {**at_home["exifInfo"], "latitude": 50.0005, "longitude": 4.0}
    away = [picture(f"p-away-{n}", "primary", 2 + n, ()) for n in range(5)]
    for item in away:
        item["exifInfo"] = {**item["exifInfo"], "latitude": 52.0, "longitude": 5.0}
    return [at_home, *away]


def test_the_dry_run_notice_counts_only_the_pictures_the_place_can_keep(
    monkeypatch: pytest.MonkeyPatch, lexicon: Lexicon
) -> None:
    from tests.household_fake import PRIMARY_KEY, FakeHousehold, immich_config

    # WHY: replaces the Immich HTTP API; the window check's own discovery stays real.
    FakeHousehold(library={PRIMARY_KEY: _library_dicts()}).install(monkeypatch)
    config = Config()
    config.immich = ImmichConfig(**immich_config())
    when = WhenLink(start=date(2025, 6, 1), end=date(2025, 6, 30))
    stale = LibraryView(pictures=(), people={}, sharpness_line=None)
    place = place_filter(
        replace(_house(kind="an animal"), where=WhereLink(scope="home_at_time")),
        AT_HOME,
        lexicon,
        BankedAsker(),
    )
    lines: list[str] = []

    def dry_run(narrowed):
        with AccessBoundClient(config.immich) as client:
            try:
                prep.prepare_for_request(
                    client,
                    config,
                    open_store(),
                    stale,
                    when,
                    today=date(2025, 6, 30),
                    dry_run=True,
                    print_line=lines.append,
                    place=narrowed,
                )
            except prep.NeedsPreparationPreview as preview:
                return preview.notice
        raise AssertionError("a dry run over unprepared pictures must preview, not finish")

    assert dry_run(place).pictures == 1
    assert lines[0].startswith("1 pictures in this period")
    assert dry_run(None).pictures == 6
