"""A short film fills its free slots from the moments it shows, videos first, spread in time (#1601).

A track day kept 2 shots of 8: one 36-minute moment of the owner's own videos, and one earlier
moment in the next village. The depth ladder was there, but the story's place bound was sized
from its weight's cap (one shot for a minor story), so every further frame was dropped before it
was ever looked at.
"""

from __future__ import annotations

import hashlib
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

    carriers = sorted(plan["carriers"], key=_taken)
    assert len(carriers) == plan["story"]["slots"] == 8
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


def test_a_thin_story_with_one_picture_a_moment_is_unchanged(tmp_path):
    days = [
        Day(date(2030, 5, 12), "Laps", TRACK, moments=3),
    ]
    source = film_source(tmp_path, days, seconds=40, span=MAY, pictures=1)

    plan = _run(source)

    assert len(plan["carriers"]) == 3
