"""A short film fills its free slots from the moments it shows, videos first, spread in time (#1601).

A track day kept 2 shots of 8: one 36-minute moment of the owner's own videos, and one earlier
moment in the next village. The depth ladder was there, but the story's place bound was sized
from its weight's cap (one shot for a minor story), so every further frame was dropped before it
was ever looked at.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from itertools import pairwise

from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.api.models import AssetType
from tests.editorial_film_fixtures import Day, film_source

MAY = (date(2030, 5, 1), date(2030, 5, 31))
TRACK = (50.30, 4.65, "Circuit Town", "Farland")
VILLAGE = (50.34, 4.71, "Next Village", "Farland")


def _apart(asset_id):
    return hashlib.sha256(asset_id.encode()).hexdigest()[:16]


def _as_videos(source, seconds=5.0):
    for asset in source.assets.values():
        asset.type = AssetType.VIDEO
        asset.duration_seconds = seconds
    return source


def _run(source, thumbnail_hash=_apart):
    """The no-model draft: the rules reader files a day as one story, the path a NAS takes."""
    ports = StructurePlannerPorts(
        judge=NoModelJudge(), thumbnail_hash=thumbnail_hash, rules=RuleStructureReader(source)
    )
    return plan_structure(source, ports).plan


def _taken(carrier) -> datetime:
    return datetime.fromisoformat(carrier["taken"])


def test_one_long_moment_of_distinct_videos_fills_the_film_spread_in_time(tmp_path):
    day = Day(date(2030, 5, 12), "Laps on the circuit", TRACK, moments=1)
    source = _as_videos(
        film_source(
            tmp_path, [day], seconds=40, span=MAY, pictures=20, picture_gap=timedelta(seconds=110)
        )
    )

    plan = _run(source)

    # The depth fill now stops on content seconds, not the picture-count slot grant
    # (#2083): twenty 5 s video shots reach "near target" well before 8 picture slots.
    carriers = sorted(plan["carriers"], key=_taken)
    assert len(carriers) > 1
    assert plan["duration_realization"]["status"] == "near_target"
    times = [_taken(c) for c in carriers]
    gaps = [(b - a).total_seconds() for a, b in pairwise(times)]
    assert min(gaps) >= 3 * 60  # spread over the 36 minutes, not a burst at one end


def test_a_day_across_two_places_fills_past_its_minor_cap(tmp_path):
    day = date(2030, 5, 12)
    days = [Day(day, "Paddock", VILLAGE, moments=1), Day(day, "Laps", TRACK, moments=1)]
    source = film_source(
        tmp_path, days, seconds=40, span=MAY, pictures=8, picture_gap=timedelta(minutes=4)
    )

    plan = _run(source)

    assert len(plan["carriers"]) > 2
    places = {c["asset_id"].split("-")[0] for c in plan["carriers"]}
    assert len(places) == 2  # the place bound still spreads the film over both places


def test_frames_that_look_alike_never_fill(tmp_path):
    day = Day(date(2030, 5, 12), "Laps on the circuit", TRACK, moments=1)
    source = _as_videos(
        film_source(
            tmp_path, [day], seconds=40, span=MAY, pictures=20, picture_gap=timedelta(seconds=110)
        )
    )

    plan = _run(source, lambda _asset: "0f0f0f0f0f0f0f0f")

    assert len(plan["carriers"]) == 1


def test_a_moment_fills_with_its_videos_before_its_stills(tmp_path):
    day = Day(date(2030, 5, 12), "Laps on the circuit", TRACK, moments=1)
    source = film_source(
        tmp_path, [day], seconds=40, span=MAY, pictures=20, picture_gap=timedelta(seconds=110)
    )
    for index, asset in enumerate(sorted(source.assets.values(), key=lambda a: a.id)):
        if index % 2 == 0:
            asset.type = AssetType.VIDEO
            asset.duration_seconds = 5.0

    plan = _run(source)

    kinds = [c["kind"] for c in plan["carriers"]]
    assert len(kinds) > 1
    assert set(kinds) == {"video"}


def test_a_timestamp_heap_counts_as_one_shot_and_the_film_goes_short(tmp_path, caplog):
    """A heap of pictures sharing one timestamp is one shot, not seventeen (#2083): the film
    honestly goes short of its target rather than deepen the same moment past its real
    material, and says so in one line."""
    day = Day(date(2030, 5, 12), "A placeholder-date heap", TRACK, moments=1)
    source = film_source(
        tmp_path, [day], seconds=600, span=MAY, pictures=17, picture_gap=timedelta(seconds=0)
    )

    with caplog.at_level("INFO", logger="immich_memories.analysis.editorial_story_depth_fill"):
        plan = _run(source)

    assert len(plan["carriers"]) == 1
    assert plan["duration_realization"]["status"] != "near_target"
    assert any("distinct shots" in record.message for record in caplog.records)


def test_a_party_evening_is_capped_by_five_minute_spacing(tmp_path):
    """Eight frames sixteen minutes apart admit at most four, the five-minute capture
    spacing pass 1 already uses (#2083): none are pixel duplicates, but a frame every two
    minutes of one evening is still a burst, not four times the material."""
    day = Day(date(2030, 5, 12), "A party evening", TRACK, moments=1)
    source = film_source(
        tmp_path, [day], seconds=600, span=MAY, pictures=8, picture_gap=timedelta(minutes=2)
    )

    plan = _run(source)

    assert 1 <= len(plan["carriers"]) <= 4


def test_a_dense_day_under_two_place_labels_fills_with_its_videos_first(tmp_path):
    """One town arriving as two label strings must still share one place (#2083): a day's
    two moments, geocoded to a short name and the long administrative string for the same
    spot, are not bounded apart, so the film fills toward its target with its videos first."""
    long_label = (TRACK[0], TRACK[1], "Circuit Town, Province de Namur, Wallonia", TRACK[3])
    day = Day(
        date(2030, 5, 12),
        "A dense track day",
        TRACK,
        moments=2,
        moment_where={1: long_label},
    )
    source = _as_videos(
        film_source(
            tmp_path, [day], seconds=600, span=MAY, pictures=10, picture_gap=timedelta(minutes=6)
        )
    )

    plan = _run(source)

    assert len(plan["carriers"]) > 2
    # One real place, not two: nothing for a bounded place to compete with.
    places = json.loads(next(source.artifact_dir.rglob("story-places.private.json")).read_text())
    assert places["scopes"] == []
    kinds = {c["kind"] for c in plan["carriers"]}
    assert kinds == {"video"}


def test_a_clean_story_of_well_spaced_moments_is_unchanged(tmp_path):
    """A story whose moments are already each their own distinct shot, well inside the
    target, is untouched by the depth fill (#2083): nothing to deepen, nothing to cut short."""
    days = [Day(date(2030, 5, 12), "Laps", TRACK, moments=5)]
    source = film_source(tmp_path, days, seconds=40, span=MAY, pictures=1)

    plan = _run(source)

    assert len(plan["carriers"]) == 5
    assert all(not c.get("depth") for c in plan["carriers"])


def test_a_thin_story_with_one_picture_a_moment_is_unchanged(tmp_path):
    days = [
        Day(date(2030, 5, 12), "Laps", TRACK, moments=3),
    ]
    source = film_source(tmp_path, days, seconds=40, span=MAY, pictures=1)

    plan = _run(source)

    assert len(plan["carriers"]) == 3


NOVEMBER = (date(2011, 11, 1), date(2011, 11, 30))


def _an_event_day(tmp_path, pictures, *, minutes=2):
    """A month whose one event fills a day: every picture is its own distinct frame."""
    day = Day(date(2011, 11, 19), "An obstacle course", moments=1)
    return film_source(
        tmp_path,
        [day],
        seconds=60,
        span=NOVEMBER,
        pictures=pictures,
        picture_gap=timedelta(minutes=minutes),
    )


def test_a_big_event_is_a_shot_for_every_five_distinct_pictures(tmp_path):
    """Twenty-one distinct pictures of one day's event were one shot, a 14 s film (#2211): the
    event is several beats, so it earns about one shot per five of its pictures."""
    plan = _run(_an_event_day(tmp_path, 21))

    taken = [_taken(c) for c in plan["carriers"]]
    assert 4 <= len(taken) <= 5
    assert taken == sorted(taken)
    assert min(b - a for a, b in pairwise(taken)) >= timedelta(minutes=5)


def test_a_big_events_favourite_is_still_one_of_its_shots(tmp_path):
    source = _an_event_day(tmp_path, 21)
    favourite = "d000-m0-p9"
    source.assets[favourite].is_favorite = True

    plan = _run(source)

    assert favourite in {c["asset_id"] for c in plan["carriers"]}


def test_a_small_event_is_still_one_shot(tmp_path):
    plan = _run(_an_event_day(tmp_path, 9))

    assert len(plan["carriers"]) == 1


def test_a_big_event_shot_in_a_dozen_seconds_is_still_one_shot(tmp_path):
    """Pictures under a second apart are one beat however many there are."""
    plan = _run(_an_event_day(tmp_path, 21, minutes=0.01))

    assert len(plan["carriers"]) == 1


def test_a_picture_the_plan_passed_over_names_the_rule_that_did(tmp_path):
    """The pool said "not used in the plan" for the event's other pictures and named no rule."""
    plan = _run(_an_event_day(tmp_path, 21))

    shown = {c["asset_id"] for c in plan["carriers"]}
    passed_over = {a: why for a, why in plan["left_out"].items() if a not in shown}
    assert len(passed_over) == 21 - len(shown)
    assert set(passed_over.values()) <= {
        "it is not its own shot: a moment earns one shot for every 5 distinct pictures, "
        "or one every five minutes",
        "the film's content seconds were spent before its turn",
    }
