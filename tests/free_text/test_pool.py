"""The pool: the pictures a request can be filmed from, filter by filter, with a verdict."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson, LibraryPicture, LibraryView
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
        ("kind of picture", 15),
        ("subject", 14),
    ]
    assert pool.verdict == "possible"


def test_a_few_pictures_are_thin_and_none_is_not_possible_with_the_step_that_emptied_it(
    lexicon: Lexicon,
) -> None:
    few = build_pool(
        _asked("our cat", main=("cat",)), _view(*_cats(3)), NOBODY, lexicon, BankedAsker()
    )
    # WHY: stands in for the model server, asked whether "cat" (the captions' subject) is a brunch.
    no_other_name = BankedAsker(*[{"reason": "banked", "choices": []}] * 3)
    none = build_pool(
        _asked("brunches", main=("brunch",)), _view(*_cats(3)), NOBODY, lexicon, no_other_name
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
    assert ("who", 2) in [(step.name, step.kept) for step in pool.funnel]


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


def test_the_place_names_a_request_says_replace_its_where_and_screens_are_left_out(
    lexicon: Lexicon,
) -> None:
    view = _view(
        _picture("there", country="Examplia", picture_kind="photograph"),
        _picture("there-video", country="Examplia", media_kind="video"),
        _picture("there-screen", country="Examplia", picture_kind="screenshot_from_computer"),
        _picture("elsewhere", country="Otherland"),
    )
    facts = LibraryFacts(places=(("country", "Examplia"),))
    asked = _asked("examplia", facts=facts, where=WhereLink(scope="near_home"))

    pool = build_pool(asked, view, MOVED, lexicon, BankedAsker())

    assert _ids(pool) == {"there", "there-video"}
    assert [step.name for step in pool.funnel] == ["library", "place names", "kind of picture"]


def test_a_named_kind_of_picture_and_the_sharpness_line_filter_mechanically(
    lexicon: Lexicon,
) -> None:
    view = _view(
        _picture("screen", picture_kind="screenshot_from_computer"),
        _picture("photo", picture_kind="photograph", sharpness=2.0),
        _picture("soft", picture_kind="photograph", sharpness=0.5),
        _picture("unmeasured", picture_kind="photograph"),
        sharpness_line=1.0,
    )
    screens = _asked("screenshots", facts=LibraryFacts(picture_kinds=("screenshots",)))
    blurry = _asked("blurry", facts=LibraryFacts(sharpness="below", sharpness_line=1.0))

    assert _ids(build_pool(screens, view, NOBODY, lexicon, BankedAsker())) == {"screen"}
    assert _ids(build_pool(blurry, view, NOBODY, lexicon, BankedAsker())) == {"soft"}


def test_first_and_last_pictures_of_each_frequent_person_are_the_whole_pool(
    lexicon: Lexicon,
) -> None:
    pat, sam = frozenset({"pat"}), frozenset({"sam"})
    view = _view(
        _picture("pat-first", "2019-01-01", people=pat),
        _picture("pat-screen", "2018-01-01", people=pat, picture_kind="screenshot_from_manual"),
        _picture("both", "2019-06-01", people=pat | sam),
        _picture("sam-last", "2020-01-01", people=sam, caption="A man on a bench"),
        people={
            "pat": LibraryPerson("pat", "Pat Example", None, None),
            "sam": LibraryPerson("sam", "Sam Example", "son", date(2018, 5, 1)),
        },
    )
    firsts = LibraryFacts(people=("pat", "sam"), extreme="first")
    faces = LibraryFacts(people=("sam",))

    first = build_pool(_asked("first", facts=firsts), view, NOBODY, lexicon, BankedAsker())
    anyone = build_pool(_asked("sam", facts=faces), view, NOBODY, lexicon, BankedAsker())

    assert _ids(first) == {"pat-first", "both"}
    assert first.verdict == "possible"
    assert _ids(anyone) == {"both", "sam-last"}


def test_the_farthest_trip_is_the_pool_whatever_the_subject(lexicon: Lexicon) -> None:
    far = [
        _picture(f"far-{n}", f"2021-08-0{n}", latitude=45.0, longitude=5.0, caption="A beach")
        for n in range(1, 4)
    ]
    view = _view(*_places().pictures, *far)
    asked = _asked("farthest", main=("cat",), facts=LibraryFacts(extreme="farthest"))

    pool = build_pool(asked, view, MOVED, lexicon, BankedAsker())
    unknown = build_pool(asked, view, NOBODY, lexicon, BankedAsker())

    assert _ids(pool) == {"far-1", "far-2", "far-3"}
    assert "subject" not in [step.name for step in pool.funnel]
    assert unknown.verdict == "not possible"


def _picks(*choices: str) -> dict[str, Any]:
    return {"reason": "banked", "choices": list(choices)}


def test_only_what_follows_a_negation_can_be_left_out_and_the_request_keeps_its_own_subject(
    lexicon: Lexicon,
) -> None:
    view = _view(
        *[_picture(f"car-{n}", caption="A blue car parked on a street") for n in range(3)],
        _picture("toy", caption="A red toy car on a rug"),
        _picture("bike", caption="A motorcycle parked by a wall"),
    )
    subject = Subject(heads=("car",), words=("car",), main=("car",), extent=("motorcycle",))
    asked = _asked("the cars I drove, no toy cars or motorcycles", subject=subject)
    # WHY: stands in for the model server; two of three answers leave out both phrases.
    asker = BankedAsker(
        _picks("toy cars", "motorcycles"), _picks("toy cars", "motorcycles"), _picks("toy cars")
    )

    pool = build_pool(asked, view, NOBODY, lexicon, asker)
    plain = build_pool(
        _asked("the cars I drove", subject=subject), view, NOBODY, lexicon, BankedAsker()
    )

    assert _ids(pool) == {"car-0", "car-1", "car-2"}
    offered = asker.questions[0][1]["properties"]["choices"]["items"]["enum"]
    assert "toy cars" in offered
    assert "the cars" not in offered
    assert _ids(plain) == {"car-0", "car-1", "car-2", "toy", "bike"}


def test_other_names_for_the_subject_carry_its_stated_quality(lexicon: Lexicon) -> None:
    def said(caption: str, count: int) -> list[LibraryPicture]:
        return [_picture(f"{caption}-{n}", caption=caption) for n in range(count)]

    view = _view(
        *said("A black kitten is playing with yarn", 3),
        *said("A black cat is sleeping", 2),
        *said("A black puss on a sofa", 1),
        *said("A white kitten on a rug", 1),
        *said("A dog is running on a beach", 3),
        *said("A woman is reading a book", 3),
    )
    subject = Subject(heads=("cat",), words=("cat",), main=("black cat",))
    # WHY: stands in for the model server; only kitten gets two votes as another name.
    asker = BankedAsker(_picks("kitten"), _picks("kitten", "dog"), _picks("kitten"))

    pool = build_pool(_asked("our black cat", subject=subject), view, NOBODY, lexicon, asker)

    assert {p.caption for p in pool.pictures} == {
        "A black kitten is playing with yarn",
        "A black cat is sleeping",
        "A black puss on a sofa",
    }
    offered = asker.questions[0][1]["properties"]["choices"]["items"]["enum"]
    assert sorted(offered) == ["dog", "kitten"]
