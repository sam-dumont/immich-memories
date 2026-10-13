"""A day the household keeps becomes its own story, named from its facts (#2486)."""

from __future__ import annotations

from collections import Counter

from immich_memories.analysis.editorial_occasions import find_occasions, spoken_list

_RELATION = {
    "Robin": "library owner",
    "Charlie": "partner",
    "Kit": "child",
    "Pat": "parent",
    "Lou": "parent",
    "Jo": "friend",
}
_BORN = {"Robin": "1987-03-14", "Kit": "2020-07-05", "Pat": "1955-04-20", "Jo": "2019-07-08"}
_CLOSE = frozenset({"Charlie", "Kit", "Pat", "Lou"})


def _find(day_people):
    return find_occasions(
        {day: Counter(people) for day, people in day_people.items()},
        relation_of=_RELATION,
        birth_dates=_BORN,
        close_family=_CLOSE,
        locale="en",
    )


def test_a_childs_birthday_is_named_with_their_age() -> None:
    found = _find({"2025-07-05": {"Kit": 6, "Robin": 2}, "2025-07-04": {"Kit": 3}})

    birthday = found["2025-07-05"]
    assert (birthday.kind, birthday.name, birthday.purpose) == (
        "birthday",
        "Kit's birthday",
        "Kit turns five",
    )
    assert "2025-07-04" not in found


def test_close_familys_visit_is_named_after_the_visitors() -> None:
    found = _find({"2025-07-07": {"Pat": 4, "Lou": 3, "Kit": 2}})

    visit = found["2025-07-07"]
    assert (visit.kind, visit.people, visit.name, visit.purpose) == (
        "visit",
        ("Pat", "Lou"),
        "Pat and Lou's visit",
        "Pat and Lou come over",
    )


def test_one_picture_of_a_visitor_is_not_a_visit() -> None:
    assert _find({"2025-07-07": {"Pat": 1, "Lou": 1}}) == {}


def test_one_picture_on_their_birth_date_is_their_birthday() -> None:
    # The date is the evidence: a film of Kit and Robin may hold one frame of both that day.
    assert _find({"2025-07-05": {"Kit": 1, "Robin": 1}})["2025-07-05"].name == "Kit's birthday"


def test_visitors_seen_equally_are_named_the_same_way_in_every_film() -> None:
    one = _find({"2025-07-07": {"Pat": 3, "Lou": 3}})["2025-07-07"].name
    other = _find({"2025-07-07": {"Lou": 3, "Pat": 3}})["2025-07-07"].name

    assert one == other == "Lou and Pat's visit"


def test_a_friends_birthday_is_theirs_not_the_households() -> None:
    assert _find({"2025-07-08": {"Jo": 5}}) == {}


def test_family_seen_most_days_lives_in_and_is_never_visiting() -> None:
    days = {f"2025-07-{d:02d}": {"Pat": 2} for d in range(1, 6)}

    assert _find(days) == {}


def test_a_birthday_outranks_a_visit_on_the_same_day() -> None:
    assert _find({"2025-07-05": {"Pat": 4, "Kit": 3}})["2025-07-05"].kind == "birthday"


def test_names_read_as_a_sentence_says_them() -> None:
    assert [spoken_list(n, "en") for n in (["Pat"], ["Pat", "Lou"], ["Pat", "Lou", "Remy"])] == [
        "Pat",
        "Pat and Lou",
        "Pat, Lou and Remy",
    ]


def test_a_birthday_films_subject_has_their_birthday_whoever_they_are_to_the_owner() -> None:
    """rc.10: a birthday film of a friend (no birth date in the registry, not family) had no
    birthday story, though the request named the day and the cut held it."""
    found = find_occasions(
        {
            "2025-08-30": Counter({"Jo": 1}),
            "2022-08-30": Counter({"Jo": 2}),
            "2025-08-31": Counter({"Jo": 4}),
        },
        relation_of=_RELATION,
        birth_dates={},
        close_family=_CLOSE,
        locale="en",
        celebrated={"Jo": "08-30"},
    )

    assert sorted(found) == ["2022-08-30", "2025-08-30"]
    assert (found["2025-08-30"].kind, found["2025-08-30"].name) == ("birthday", "Jo's birthday")
    assert found["2025-08-30"].people == ("Jo",)
