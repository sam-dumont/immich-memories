"""The pool: the pictures a request can be filmed from, filter by filter, with a verdict."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.pool import Translation, build_pool
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import Subject
from tests.free_text.banked import BankedAsker

NOBODY = Household({})


def _picture(asset_id: str, day: str = "2020-05-01", **fields: Any) -> LibraryPicture:
    taken_at = datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC)
    fields.setdefault("media_kind", "photo")
    return LibraryPicture(asset_id=asset_id, taken_at=taken_at, **fields)


def _view(*pictures: LibraryPicture, **fields: Any) -> LibraryView:
    fields.setdefault("people", {})
    fields.setdefault("sharpness_line", None)
    return LibraryView(pictures=tuple(sorted(pictures, key=lambda p: p.taken_at)), **fields)


def _asked(request: str, *, main: tuple[str, ...] = (), **parts: Any) -> Translation:
    return Translation(
        reading=parts.pop("reading", Reading(request=request)),
        who=parts.pop("who", WhoLink()),
        when=parts.pop("when", WhenLink()),
        where=parts.pop("where", WhereLink()),
        facts=parts.pop("facts", LibraryFacts()),
        subject=parts.pop("subject", Subject(heads=main, words=main, main=main)),
    )


def _cats(count: int, start: str = "2020-01-01") -> list[LibraryPicture]:
    first = date.fromisoformat(start)
    return [
        _picture(f"cat-{n}", str(first + timedelta(days=n)), caption="A black cat is sleeping")
        for n in range(count)
    ]


def _ids(pool: Any) -> set[str]:
    return {picture.asset_id for picture in pool.pictures}


def test_the_pool_is_the_dated_pictures_whose_caption_is_about_the_subject(
    lexicon: Lexicon,
) -> None:
    view = _view(
        *_cats(14),
        _picture("held", "2020-01-03", caption="A man holding a cat in a garden"),
        _picture("before", "2019-06-01", caption="A cat on a windowsill"),
    )
    asked = _asked(
        "our cat since 2020",
        main=("cat",),
        when=WhenLink(start=date(2020, 1, 1)),
    )

    pool = build_pool(asked, view, NOBODY, lexicon, BankedAsker())

    assert _ids(pool) == {f"cat-{n}" for n in range(14)}
    assert [(step.name, step.kept) for step in pool.funnel] == [
        ("library", 16),
        ("when", 15),
        ("subject", 14),
    ]
    assert pool.verdict == "possible"


def test_a_few_pictures_are_thin_and_none_is_not_possible_with_the_step_that_emptied_it(
    lexicon: Lexicon,
) -> None:
    few = build_pool(
        _asked("our cat", main=("cat",)), _view(*_cats(3)), NOBODY, lexicon, BankedAsker()
    )
    none = build_pool(
        _asked("brunches", main=("brunch",)), _view(*_cats(3)), NOBODY, lexicon, BankedAsker()
    )

    assert few.verdict == "thin"
    assert "3 pictures" in few.why
    assert none.verdict == "not possible"
    assert "subject" in none.why
    assert "brunch" in none.why


def _at(asset_id: str, when: str, **fields: Any) -> LibraryPicture:
    fields.setdefault("media_kind", "photo")
    return LibraryPicture(asset_id=asset_id, taken_at=datetime.fromisoformat(when), **fields)


def test_a_named_person_is_present_anywhere_in_the_episode_of_their_recognised_face(
    lexicon: Lexicon,
) -> None:
    view = _view(
        _at("face", "2020-05-01T12:00+00:00", people=frozenset({"kid"})),
        _at("from-behind", "2020-05-01T13:15+00:00"),
        _at("hours-later", "2020-05-01T16:00+00:00"),
        _at("other-day", "2020-06-01T12:00+00:00", people=frozenset({"visitor"})),
    )
    asked = _asked("my son", who=WhoLink(present=("kid",), anchors=("kid",)))

    pool = build_pool(asked, view, NOBODY, lexicon, BankedAsker())

    assert _ids(pool) == {"face", "from-behind"}
    assert pool.funnel[-1].name == "who"


def test_company_needs_a_caption_naming_people_of_that_kind(lexicon: Lexicon) -> None:
    view = _view(
        _picture("kids", caption="Two children playing in a park"),
        _picture("kid", caption="A kid on a swing in a park"),
        _picture("friend", caption="A friend sitting on a bench in a park"),
        _picture("empty", caption="An empty park at dusk"),
    )
    children = _asked("at the park with kids", main=("park",), who=WhoLink(company="children"))
    people = _asked("the park with friends", main=("park",), who=WhoLink(company="people"))

    with_kids = build_pool(children, view, NOBODY, lexicon, BankedAsker())
    with_people = build_pool(people, view, NOBODY, lexicon, BankedAsker())

    assert _ids(with_kids) == {"kids", "kid"}
    assert _ids(with_people) == {"kids", "kid", "friend"}
    assert with_kids.funnel[-1].name == "company"


OLD_HOME = Home(50.0, 4.0, since=None, until=date(2020, 1, 1))
NEW_HOME = Home(51.0, 5.0, since=date(2020, 1, 1), until=None)
MOVED = Household({}, homes=(OLD_HOME, NEW_HOME))


def _where(scope: str, home: Home | None = None) -> Translation:
    return _asked("somewhere", where=WhereLink(scope=scope, home=home))


def _places() -> LibraryView:
    return _view(
        _picture("old-house", "2019-05-01", latitude=50.0005, longitude=4.0),
        _picture("old-town", "2019-05-02", latitude=50.05, longitude=4.0),
        _picture("new-house", "2021-05-01", latitude=51.0005, longitude=5.0),
        _picture("old-house-later", "2021-05-02", latitude=50.0005, longitude=4.0),
        _picture("no-gps", "2021-05-03"),
        _picture("trip-1", "2021-07-01", latitude=52.0, longitude=5.0),
        _picture("trip-2", "2021-07-02", latitude=52.0, longitude=5.0),
        _picture("trip-3", "2021-07-03", latitude=52.0, longitude=5.0),
    )


def test_where_keeps_the_pictures_taken_in_its_place_and_no_gps_is_no_evidence_of_elsewhere(
    lexicon: Lexicon,
) -> None:
    def where(scope: str, home: Home | None = None) -> set[str]:
        return _ids(build_pool(_where(scope, home), _places(), MOVED, lexicon, BankedAsker()))

    assert where("home", OLD_HOME) == {"old-house", "old-house-later", "no-gps"}
    assert where("home_at_time") == {"old-house", "new-house", "no-gps"}
    assert where("near_home") == {"old-house", "old-town", "new-house", "no-gps"}
    assert where("trips") == {"trip-1", "trip-2", "trip-3"}
    assert where("anywhere") == {p.asset_id for p in _places().pictures}


def test_away_from_home_without_a_known_home_cannot_be_told_and_says_so(
    lexicon: Lexicon,
) -> None:
    pool = build_pool(_where("trips"), _places(), NOBODY, lexicon, BankedAsker())

    assert pool.verdict == "not possible"
    assert "no home" in pool.why
