"""A recurring kind inside one partition is one story's worth of pictures.

Several starred stories of the same kind in one month (three evenings of the same activity at
the same place) each used to take the full depth a major story gets, as much as a ten-day trip.
Now every member keeps its own picture and the depth the kind earns as ONE story goes to its
heaviest member. Trips and big family stories never fold.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.analysis.editorial_story_planner import funding_order
from immich_memories.analysis.editorial_story_slots import allocate_slots
from immich_memories.config_models_editorial import EditorialPeopleConfig
from tests.e2e.fake_library import HOME as FIXTURE_HOME
from tests.e2e.fake_library import LIBRARY


def _story(key, *, day, weight="major", moments=1, favourites=0, depth_to=None):
    row = {
        "key": key,
        "episodes": [f"E-{key}"],
        "weight": weight,
        "gate": "remarkable",
        "first_day": day,
        "seen": {"days": 1, "moments": moments, "pictures": moments, "favourites": favourites},
    }
    if depth_to is not None:
        row["depth_to"] = depth_to
    return row


def _year(*, folded: bool):
    """A synthetic year shaped like a busy family library: three long trips, a recurring kind
    of evening three times in one month, eight small starred days and sixty quiet ones."""
    kind = "evening-a" if folded else None
    majors = [
        _story("trip-spring", day="2030-04-04", moments=80, favourites=120),
        _story("trip-summer", day="2030-07-20", moments=60, favourites=110),
        _story("trip-autumn", day="2030-10-28", moments=50, favourites=70),
        _story("evening-a", day="2030-11-09", moments=20, favourites=30, depth_to=kind),
        _story("evening-b", day="2030-11-15", moments=10, favourites=6, depth_to=kind),
        _story("evening-c", day="2030-11-21", moments=9, favourites=12, depth_to=kind),
        *(
            _story(f"small-{n}", day=f"2030-{n + 1:02d}-10", moments=m, favourites=4)
            for n, m in enumerate((7, 6, 5, 5, 4, 3, 3, 2))
        ),
    ]
    minors = [
        _story(f"quiet-{n:02d}", day=f"2030-{n // 5 + 1:02d}-{n % 5 * 5 + 2:02d}", weight="minor")
        for n in range(60)
    ]
    capacity = {s["key"]: s["seen"]["moments"] for s in majors} | {s["key"]: 3 for s in minors}
    return funding_order(majors + minors), capacity


def test_a_recurring_kind_gets_one_storys_depth_and_every_member_keeps_its_picture():
    before = allocate_slots(_year(folded=False)[0], 175, _year(folded=False)[1])
    after = allocate_slots(_year(folded=True)[0], 175, _year(folded=True)[1])

    assert before["evening-b"] > 1 and before["evening-c"] > 1
    assert after["evening-b"] == 1
    assert after["evening-c"] == 1
    assert after["evening-a"] >= before["evening-a"]
    # the kind deepens as one story of its weight: its holder no deeper than the trips
    assert after["evening-a"] <= min(
        after[t] for t in ("trip-spring", "trip-summer", "trip-autumn")
    )
    for trip in ("trip-spring", "trip-summer", "trip-autumn"):
        assert after[trip] > before[trip]
    assert sum(after.values()) == sum(before.values()) == 175


# --- the rules reader names a recurring kind ------------------------------------------------

HOME = (40.0, 10.0)
VENUE = (40.018, 10.0)  # 2 km north of home
ACROSS_TOWN = (39.919, 10.0)  # 9 km south of home: still home, 11 km from the venue
AWAY = (40.2, 10.0)  # 22 km from home: a trip

START = datetime(2030, 3, 1)
# day counted from START -> (pictures, favourites, activity, where)
EVENINGS = {
    3: (40, 12, "concert", VENUE),
    10: (40, 5, "concert", VENUE),
    17: (40, 4, "concert", VENUE),
    24: (40, 4, "concert", ACROSS_TOWN),
}
QUIET = dict.fromkeys((1, 5, 7, 12, 14, 19, 21, 26, 28), (4, 0, "posing", HOME))


def _read(month, *, gps=True, family_days=()):
    assets, moments, audience, gps_of = {}, {}, {}, {}
    for day, (pictures, favourites, activity, where) in month.items():
        for group in range(2):
            ids = []
            for n in range(pictures // 2):
                asset_id = f"d{day:02}-g{group}-{n:03}"
                taken = START + timedelta(days=day - 1, hours=19 + group, minutes=n)
                assets[asset_id] = SimpleNamespace(
                    id=asset_id,
                    file_created_at=taken,
                    is_favorite=group == 0 and n < favourites,
                    is_video=False,
                    exif_info=SimpleNamespace(city=f"town-{where[0]}"),
                    people=[],
                )
                audience[asset_id] = SimpleNamespace(heads=[("activity", activity)])
                if gps:
                    gps_of[asset_id] = where
                ids.append(asset_id)
            moments[f"M{day:02}{group}"] = tuple(ids)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids=moments,
        gps=gps_of,
        annotations={
            a: f"{asset.file_created_at.isoformat()} | posing | with Person A (partner; inner circle)"
            for a, asset in assets.items()
            if (asset.file_created_at - START).days + 1 in family_days
        },
        audience_annotations=audience,
        config=SimpleNamespace(
            trips=SimpleNamespace(homebase_latitude=HOME[0], homebase_longitude=HOME[1]),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
        ),
        intent=SimpleNamespace(
            product="year_in_review",
            partition_for=lambda day: SimpleNamespace(key=f"month-{day.month}"),
        ),
        case=SimpleNamespace(product="year_in_review", people=()),
        people=None,
    )

    def enrich(episodes):
        hints = {}
        for episode in episodes:
            members = [a for m in episode.moments for a in moments[m]]
            day = assets[members[0]].file_created_at.date()
            hints[episode.key] = {
                "day": day.isoformat(),
                "moments": len(episode.moments),
                "pictures": len(members),
                "favourites": sum(assets[a].is_favorite for a in members),
                "gate": "remarkable",
            }
        return hints

    story = RuleStructureReader(source).read_story(
        None, evidence=[], enrich=enrich, record=lambda _record: None
    )
    by_day = {}
    for row in story.stories:
        for key in row["episodes"]:
            episode = next(e for e in story.episodes if e.key == key)
            taken = assets[moments[episode.moments[0]][0]].file_created_at
            by_day[(taken - START).days + 1] = row
    return by_day


def test_the_same_kind_at_one_place_in_one_month_gives_its_depth_to_the_heaviest():
    stories = _read(EVENINGS | QUIET)

    heaviest = stories[3]["key"]
    assert stories[3].get("depth_to") == heaviest
    assert stories[10].get("depth_to") == heaviest
    assert stories[17].get("depth_to") == heaviest


def test_the_same_kind_at_another_place_keeps_its_own_depth():
    assert "depth_to" not in _read(EVENINGS | QUIET)[24]


def test_a_label_on_ordinary_days_folds_nothing():
    """The quiet days all read "posing" at home, but none is dense: a label alone links nothing."""
    stories = _read(EVENINGS | QUIET)

    assert all("depth_to" not in stories[day] for day in QUIET)


def test_without_gps_the_same_place_name_links_the_kind():
    stories = _read(EVENINGS | QUIET, gps=False)

    assert stories[10].get("depth_to") == stories[3]["key"]
    assert "depth_to" not in stories[24]


def test_the_same_kind_in_another_month_is_not_the_same_thread():
    stories = _read({3: EVENINGS[3], 17: EVENINGS[17], 41: EVENINGS[10]} | QUIET)

    assert stories[3].get("depth_to") == stories[3]["key"]
    assert "depth_to" not in stories[41]


def test_the_same_kind_away_from_home_is_a_trip_and_never_folds():
    stories = _read({3: (40, 12, "concert", AWAY), 10: (40, 5, "concert", AWAY)} | QUIET)

    assert "depth_to" not in stories[3]
    assert "depth_to" not in stories[10]


def test_a_big_family_day_of_the_same_kind_keeps_all_of_its_depth():
    """A birth-sized day (dense and full of close family) beside two smaller starred days of the
    same kind: it never folds, so it keeps every picture it would have had without the rule."""
    month = {
        3: (80, 40, "posing", VENUE),
        10: (40, 5, "posing", VENUE),
        17: (40, 4, "posing", VENUE),
    }
    stories = _read(month | QUIET, family_days=(3,))
    rows = [row | {"first_day": f"day-{day:02}"} for day, row in sorted(stories.items())]
    capacity = {s["key"]: 12 for s in rows}
    without = [{k: v for k, v in s.items() if k != "depth_to"} for s in rows]

    before = allocate_slots(funding_order(without), 20, capacity)
    after = allocate_slots(funding_order(rows), 20, capacity)

    assert "depth_to" not in stories[3]
    assert stories[17].get("depth_to") == stories[10]["key"]
    assert after[stories[3]["key"]] >= before[stories[3]["key"]]


def test_the_public_fixture_month_folds_nothing():
    """The CC0 demo month (a garden birthday, a week at a lake, a day in the woods, ordinary
    days at home), each scene labelled by its own kind: no kind repeats densely enough to fold."""
    assets, moments, audience, gps_of = {}, {}, {}, {}
    for picture in LIBRARY:
        taken = datetime.fromisoformat(picture.taken_at.replace("Z", "+00:00")).replace(tzinfo=None)
        assets[picture.asset_id] = SimpleNamespace(
            id=picture.asset_id,
            file_created_at=taken,
            is_favorite=picture.is_favorite,
            is_video=picture.is_video,
            exif_info=SimpleNamespace(city=picture.place.city),
            people=[],
        )
        audience[picture.asset_id] = SimpleNamespace(
            heads=[("activity", picture.scene.split("-")[0])]
        )
        gps_of[picture.asset_id] = (picture.place.latitude, picture.place.longitude)
        moments.setdefault(f"M-{picture.scene}", []).append(picture.asset_id)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids={k: tuple(v) for k, v in moments.items()},
        gps=gps_of,
        annotations={},
        audience_annotations=audience,
        config=SimpleNamespace(
            trips=SimpleNamespace(
                homebase_latitude=FIXTURE_HOME.latitude, homebase_longitude=FIXTURE_HOME.longitude
            ),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
        ),
        intent=SimpleNamespace(
            product="monthly_highlights",
            partition_for=lambda day: SimpleNamespace(key=f"month-{day.month}"),
        ),
        case=SimpleNamespace(product="monthly_highlights", people=()),
        people=None,
    )

    def enrich(episodes):
        hints = {}
        for episode in episodes:
            members = [a for m in episode.moments for a in source.moment_asset_ids[m]]
            hints[episode.key] = {
                "day": assets[members[0]].file_created_at.date().isoformat(),
                "moments": len(episode.moments),
                "pictures": len(members),
                "favourites": sum(assets[a].is_favorite for a in members),
                "gate": "remarkable",
            }
        return hints

    story = RuleStructureReader(source).read_story(
        None, evidence=[], enrich=enrich, record=lambda _record: None
    )

    assert story.stories
    assert not any("depth_to" in row for row in story.stories)
    assert story.audit["same_kind"] == []


def test_a_kind_whose_holder_left_the_film_lets_its_members_deepen_again():
    """A holder with no playable picture never reaches the allocation; its kind is then no kind."""
    stories, capacity = _year(folded=True)
    stories = [s for s in stories if s["key"] != "evening-a"]

    granted = allocate_slots(stories, 175, capacity)

    assert granted["evening-b"] > 1
