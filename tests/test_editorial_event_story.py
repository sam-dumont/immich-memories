"""A dense one-off inside an ordinary day is its own event story (no model).

An evening that changes activity and place from the rest of its day, photographed densely in
more than one burst, used to share one picture with the week of ordinary days around it. Now it
is its own story, funded first among stories of its weight, with the two pictures the minor word
allows. Nothing about the kind of event is read: a race, a concert, a graduation and a prize
evening look the same to this rule, and a label, a single burst or a screenshot alone never
makes one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.analysis.editorial_story_planner import funding_order
from immich_memories.analysis.editorial_story_slots import allocate_slots
from immich_memories.config_models_editorial import EditorialPeopleConfig
from tests.e2e.fake_library import LIBRARY


def _story(key, *, day, weight="minor", moments=1, favourites=0, **extra):
    return {
        "key": key,
        "episodes": [f"E-{key}"],
        "weight": weight,
        "gate": "remarkable",
        "first_day": day,
        "seen": {"days": 1, "moments": moments, "pictures": moments, "favourites": favourites},
        **extra,
    }


def test_an_event_takes_its_two_pictures_first_even_when_the_majors_drain_the_film():
    majors = [
        _story(f"major-{n}", day=f"2030-0{n + 1}-01", weight="major", moments=30) for n in range(4)
    ]
    quiet = [_story(f"quiet-{n}", day=f"2030-06-{n + 10}", moments=4) for n in range(5)]
    event = _story("event", day="2030-06-20", moments=3, event=True, reserve=2)
    stories = funding_order([*majors, *quiet, event])
    capacity = {s["key"]: s["seen"]["moments"] for s in stories}

    granted = allocate_slots(stories, 20, capacity)

    assert granted["event"] == 2
    assert all(granted[s["key"]] <= 1 for s in quiet)


# --- the rules reader finds the event ---------------------------------------------------------

HOME = (40.0, 10.0)
ACROSS_TOWN = (40.03, 10.0)  # 3 km from home: another place, still at home
START = datetime(2030, 3, 1)
QUIET = {day: [(9, 4, 2, "posing", HOME)] for day in (1, 3, 5, 8, 10, 12, 15, 17, 19, 22, 24, 26)}


def _read(days, *, gps=True, printed=None, starred=(), family=()):
    """Read a synthetic month. `days` maps a day to its episodes, each
    (hour, pictures, bursts, activity label, where); `where` None means no GPS."""
    assets, moments, audience, gps_of = {}, {}, {}, {}
    for day, episodes in days.items():
        for hour, pictures, bursts, activity, where in episodes:
            per_burst = max(1, pictures // bursts)
            for burst in range(bursts):
                ids = []
                for n in range(per_burst):
                    asset_id = f"a{len(assets):05}"
                    taken = START + timedelta(days=day - 1, hours=hour, minutes=burst * 20 + n % 9)
                    city = "home-town" if where in (HOME, None) else f"town-{where[0]}"
                    assets[asset_id] = SimpleNamespace(
                        id=asset_id,
                        file_created_at=taken,
                        is_favorite=day in starred and n < 3,
                        is_video=False,
                        exif_info=SimpleNamespace(city=city, place_name=None),
                        people=[],
                    )
                    audience[asset_id] = SimpleNamespace(heads=[("activity", activity)])
                    if gps and where is not None:
                        gps_of[asset_id] = where
                    ids.append(asset_id)
                moments[f"M{len(moments):04}"] = tuple(ids)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids=moments,
        gps=gps_of,
        annotations={
            a: f"{x.file_created_at.isoformat()} | with Person A (partner; inner circle)"
            for a, x in assets.items()
            if (x.file_created_at - START).days + 1 in family
        },
        audience_annotations=audience,
        config=SimpleNamespace(
            trips=SimpleNamespace(homebase_latitude=HOME[0], homebase_longitude=HOME[1]),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
        ),
        intent=SimpleNamespace(product="year_in_review"),
        case=SimpleNamespace(product="year_in_review", people=()),
        people=None,
    )

    def enrich(episodes):
        hints = {}
        for episode in episodes:
            members = [a for m in episode.moments for a in moments[m]]
            hints[episode.key] = {
                "day": assets[members[0]].file_created_at.date().isoformat(),
                "moments": len(episode.moments),
                "pictures": len(members),
                "favourites": sum(assets[a].is_favorite for a in members),
                "gate": "remarkable",
            }
        return hints

    reader = RuleStructureReader(source, printed=printed)
    story = reader.read_story(None, evidence=[], enrich=enrich, record=lambda _record: None)
    first_asset = {e.key: moments[e.moments[0]][0] for e in story.episodes}
    return [
        row
        | {"hours": sorted({assets[first_asset[k]].file_created_at.hour for k in row["episodes"]})}
        for row in story.stories
    ]


def _event_rows(stories):
    return [row for row in stories if row.get("event")]


# An ordinary Friday: a morning at home, an evening across town photographed densely in two
# bursts 20 minutes apart; the next day a short clip at home.
EVENING_OUT = {
    6: [(9, 6, 2, "working", HOME), (19, 40, 2, "celebration", ACROSS_TOWN)],
    7: [(12, 3, 1, "playing", HOME)],
}


def test_a_dense_evening_elsewhere_is_its_own_event_story():
    stories = _read(QUIET | EVENING_OUT)

    events = _event_rows(stories)
    assert len(events) == 1
    assert events[0]["hours"] == [19]
    assert events[0]["weight"] == "minor"
    week = next(
        row
        for row in stories
        if 9 in row["hours"] and row is not events[0] and len(row["episodes"]) > 1
    )
    assert all(key not in week["episodes"] for key in events[0]["episodes"])


EIGHT_KM = (40.072, 10.0)  # 8 km from home: another place, still inside the home radius
AWAY = (40.3, 10.0)  # 33 km: a trip

# Written before the rule ran. Each case replaces day 6 of an ordinary week at home; day 7 is a
# short clip at home. (hour, pictures, bursts, activity label, where); where None = no GPS.
ORDINARY_OR_NOT = {
    "a cake shot 40 times in one burst at home": (
        [(9, 5, 2, "eating-drinking", HOME), (16, 40, 1, "celebration", HOME)],
        False,
    ),
    "a pet shot 30 times in three bursts at home": (
        [(9, 6, 2, "posing", HOME), (15, 30, 3, "animal-nature", HOME)],
        False,
    ),
    "a sunset shot 45 times in one burst across town": (
        [(9, 6, 2, "working", HOME), (20, 45, 1, "sightseeing", ACROSS_TOWN)],
        False,
    ),
    "an ordinary meal out, 8 shots": (
        [(9, 6, 2, "working", HOME), (19, 8, 2, "eating-drinking", ACROSS_TOWN)],
        False,
    ),
    "a dense evening of the same activity as the morning": (
        [(9, 6, 2, "celebration", HOME), (19, 40, 2, "celebration", ACROSS_TOWN)],
        False,
    ),
    "the dog at the park next door, 300 m away but another town name": (
        [(9, 6, 2, "posing", HOME), (17, 40, 3, "animal-nature", (40.003, 10.0))],
        False,
    ),
    "a wall socket labelled as sport, one picture": ([(11, 1, 1, "sport-active", HOME)], False),
    "a cake burst with no GPS, the whole day": ([(16, 40, 1, "celebration", None)], False),
    "a graduation afternoon 8 km away, four bursts": (
        [(9, 6, 2, "working", HOME), (14, 60, 4, "celebration", EIGHT_KM)],
        True,
    ),
    "a dinner out photographed like an occasion (a documented limit)": (
        [(9, 6, 2, "working", HOME), (19, 40, 3, "eating-drinking", ACROSS_TOWN)],
        True,
    ),
    "a concert day with no GPS, three bursts": ([(20, 40, 3, "performing", None)], True),
}


@pytest.mark.parametrize("case", ORDINARY_OR_NOT)
def test_only_a_dense_distinct_one_off_becomes_an_event(case):
    day, promoted = ORDINARY_OR_NOT[case]

    events = _event_rows(_read(QUIET | EVENING_OUT | {6: day}))

    assert bool(events) is promoted


def test_a_dense_evening_on_a_trip_stays_inside_the_trip():
    trip = {
        6: [(9, 20, 2, "sightseeing", AWAY), (19, 40, 2, "celebration", (40.33, 10.0))],
        7: [(12, 20, 2, "posing", AWAY)],
    }

    assert _event_rows(_read(QUIET | trip)) == []


def test_a_story_the_owner_starred_three_times_keeps_its_evening():
    """Three favourites already make the story major: its evening has the depth it needs."""
    assert _event_rows(_read(QUIET | EVENING_OUT, starred=(6,))) == []


def _screens(*shown):
    """A fake of Immich's OCR search: (hours after the evening's last picture, words on screen)."""
    evening_end = START + timedelta(days=5, hours=19, minutes=29)

    # WHY: stands in for Immich's OCR metadata search (a read over the network) with the screens
    # and documents a library holds after the evening.
    def printed_near(word, after, before):
        return any(
            after <= evening_end + timedelta(hours=h) <= before and word in words
            for h, words in shown
        )

    return printed_near


def test_a_result_on_a_screen_the_next_morning_adds_one_picture():
    events = _event_rows(_read(QUIET | EVENING_OUT, printed=_screens((12, {"result", "km"}))))

    assert [e["reserve"] for e in events] == [3]


def test_a_screen_two_days_later_or_without_a_result_word_adds_nothing():
    late = _event_rows(_read(QUIET | EVENING_OUT, printed=_screens((40, {"result"}))))
    wordless = _event_rows(_read(QUIET | EVENING_OUT, printed=_screens((12, {"km", "min"}))))

    assert [e["reserve"] for e in late] == [2]
    assert [e["reserve"] for e in wordless] == [2]


def test_a_screen_with_only_a_record_abbreviation_adds_nothing():
    """ "PR" or "PB" belongs to some activities' slang and is a common abbreviation besides."""
    events = _event_rows(_read(QUIET | EVENING_OUT, printed=_screens((12, {"PR", "PB"}))))

    assert [e["reserve"] for e in events] == [2]


def test_a_result_screen_never_makes_an_event_on_its_own():
    """An exam morning with three pictures and a certificate on screen the next day."""
    exam = {6: [(9, 3, 1, "working", HOME)], 7: [(12, 3, 1, "playing", HOME)]}

    assert _event_rows(_read(QUIET | exam, printed=_screens((12, {"certificate"})))) == []


def test_a_birth_sized_day_stays_whole_and_keeps_its_depth():
    """Dense and full of close family: the big-story floor already makes it major, so the day
    is not cut into an event and the rest; the allocation gives it what it had."""
    stories = _read(QUIET | EVENING_OUT, family=(6, 7))

    assert _event_rows(stories) == []
    story = next(row for row in stories if 19 in row["hours"])
    assert story["weight"] == "major"


def test_the_public_fixture_month_has_no_event():
    """The CC0 demo month, each scene labelled by its own kind: nothing inside an ordinary day
    is dense enough, in bursts enough, to stand apart."""
    scenes: dict[tuple, int] = {}
    for picture in LIBRARY:
        taken = datetime.fromisoformat(picture.taken_at.replace("Z", "+00:00"))
        where = (picture.place.latitude, picture.place.longitude)
        shape = (taken.day, taken.hour, picture.scene.split("-")[0], where)
        scenes[shape] = scenes.get(shape, 0) + 1
    days: dict[int, list] = {}
    for (day, hour, label, where), pictures in scenes.items():
        days.setdefault(day, []).append((hour, pictures, 1, label, where))

    assert _event_rows(_read(days)) == []
