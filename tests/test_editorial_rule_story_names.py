"""The rules reader names a stay away a trip only by the install's own trip rule (#2486)."""

from __future__ import annotations

from immich_memories.analysis.editorial_rule_story_names import StoryFacts, name_stories

_RULE = (50.0, 2)


def _fact(days, places, *, reach=None, album=None) -> StoryFacts:
    return StoryFacts(
        days=tuple(days),
        places=tuple(places),
        people=(),
        album=album,
        farthest=places[-1] if places else None,
        reach_km=reach,
    )


def _named(stories_facts, away_keys, rule=_RULE) -> dict[str, dict]:
    stories = [{"key": key, "episodes": [key]} for key, _ in stories_facts]
    facts = dict(stories_facts)
    name_stories(
        stories,
        facts_of=lambda story: facts[story["key"]],
        away=lambda story: story["key"] in away_keys,
        trip_rule=rule,
    )
    return {story["key"]: story for story in stories}


def test_an_evening_out_near_home_is_a_day_not_a_trip() -> None:
    named = _named([("out", _fact(["2025-07-04"], ["Tervuren"], reach=11.0))], {"out"})

    assert named["out"]["title"] == "Tervuren, Friday 4 July"
    assert named["out"]["purpose"] == "A day out: Tervuren"
    assert (named["out"]["occasion"], named["out"]["trip"]) == (None, None)


def test_two_days_out_either_side_of_a_day_at_home_are_two_outings() -> None:
    # The reader lists a stretch's days at home first: the two stays away sit side by side.
    named = _named(
        [
            ("home", _fact(["2025-07-05"], ["Brussels"])),
            ("evening", _fact(["2025-07-04"], ["Tervuren"], reach=60.0)),
            ("sunday", _fact(["2025-07-06"], ["Overijse", "Tervuren"], reach=60.0)),
        ],
        {"evening", "sunday"},
    )

    assert named["evening"]["title"] == "Tervuren, Friday 4 July"
    assert named["sunday"]["title"] == "Tervuren, Sunday 6 July"
    assert named["home"]["title"] == "Brussels, Saturday 5 July"


def test_a_long_stay_far_away_is_a_trip_in_legs_named_by_its_album() -> None:
    named = _named(
        [
            ("south", _fact(["2025-07-12", "2025-07-15"], ["Copenhagen", "Gränna"], reach=900.0)),
            (
                "north",
                _fact(
                    ["2025-07-16", "2025-07-20"],
                    ["Uppsala", "Nordkapp"],
                    reach=2600.0,
                    album="The road north",
                ),
            ),
        ],
        {"south", "north"},
    )

    assert {s["trip"] for s in named.values()} == {"The road north"}
    assert [named[k]["title"] for k in ("south", "north")] == [
        "Copenhagen to Gränna",
        "Uppsala to Nordkapp",
    ]
    assert {s["occasion"] for s in named.values()} == {"leg"}


def test_the_trip_rule_is_the_installs_own() -> None:
    weekend = [("weekend", _fact(["2025-07-12", "2025-07-13"], ["Ghent"], reach=55.0))]

    assert _named(weekend, {"weekend"})["weekend"]["trip"] == "Trip to Ghent"
    assert _named(weekend, {"weekend"}, rule=(80.0, 2))["weekend"]["trip"] is None


def test_without_a_home_a_long_enough_stay_away_is_still_a_trip() -> None:
    named = _named([("away", _fact(["2025-07-12", "2025-07-14"], ["Ghent"]))], {"away"})

    assert named["away"]["trip"] == "Trip to Ghent"
