"""A custom film over several date ranges gives every year of its span that holds material a voice.

Owner ruling 2026-09-05: one year of a ten-year renovation is not the memory that was asked for.
The allocation grants each year its one picture, and no pass that cuts for length or taste may
take a year's only shot away.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_story_trim import trim_to_timing_budget
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.processing.editorial_timing import build_editorial_timing_policy
from immich_memories.timeperiod import DateRange
from tests.editorial_film_fixtures import HOME, SEASIDE, Day, film_source

BRIEF = "The garden renovation"
OLDGATE = (43.5, 9.5, "Oldgate", "Farland")


def _renovation(tmp_path, days):
    """A custom film with a written subject over one spring in each of 2018 and 2019."""
    source = film_source(
        tmp_path, days, seconds=40, span=(date(2018, 1, 1), date(2019, 12, 31)), product="custom"
    )
    ranges = tuple(
        DateRange(datetime(year, 3, 1, tzinfo=UTC), datetime(year, 6, 30, 23, 59, 59, tzinfo=UTC))
        for year in (2018, 2019)
    )
    return replace(
        source,
        case=replace(source.case, ranges=ranges, brief=BRIEF),
        intent=build_editorial_intent("custom", ranges, brief=BRIEF),
    )


def _plan(source) -> dict:
    return plan_structure(
        source,
        StructurePlannerPorts(
            judge=NoModelJudge(),
            # WHY: no preview hashes in a fixture library; the duplicate review has nothing to read.
            thumbnail_hash=lambda _asset: None,
            rules=RuleStructureReader(source),
        ),
    ).plan


def _years(source) -> list[int]:
    plan = _plan(source)
    return sorted(source.assets[c["asset_id"]].file_created_at.year for c in plan["carriers"])


def test_a_starred_picture_back_from_the_place_bound_never_takes_a_years_only_shot(tmp_path):
    """2019 is one starred week away, at two places, so the place bound holds some of its stars
    back; 2018 is one quiet day at home that nothing vouches for."""
    week = date(2019, 4, 8)
    away = [
        Day(week + timedelta(days=n), f"Works day {n + 1}", SEASIDE if n < 4 else OLDGATE, 3)
        for n in range(6)
    ]
    source = _renovation(
        tmp_path,
        [Day(date(2018, 4, 7), "Garden works", HOME), *(replace(d, starred=True) for d in away)],
    )

    years = _years(source)

    assert years.count(2018) == 1
    assert years.count(2019) == len(years) - 1


def test_a_years_only_shot_is_not_dropped_as_filler(tmp_path):
    """2018 holds one quiet day whose frames the heads read as a screen, and nothing vouches for
    it; the filler drop would leave the year without a shot."""
    starred = [
        Day(date(2019, 4, 6) + timedelta(days=7 * n), f"Works day {n + 1}", starred=True)
        for n in range(5)
    ]
    source = _renovation(tmp_path, [Day(date(2018, 4, 7), "Garden works"), *starred])
    for asset_id, row in list(source.audience_annotations.items()):
        kind = "screen_or_document" if asset_id.startswith("d000") else "people_moment"
        source.audience_annotations[asset_id] = replace(
            row, heads=(*row.heads, ("frame_kind", kind))
        )

    years = _years(source)

    assert years.count(2018) == 1


def _titled(tmp_path):
    """A title per month shown leaves 30 seconds too little for the draft: the trim cuts, and
    2018's one quiet day is its lightest story."""
    starred = [
        Day(date(2019, 3, 2) + timedelta(days=9 * n), f"Works day {n + 1}", starred=True)
        for n in range(12)
    ]
    source = _renovation(tmp_path, [Day(date(2018, 4, 7), "Garden works"), *starred])
    source.config.title_screens.enabled = True
    return replace(
        source,
        case=replace(source.case, target_seconds=30),
        render_timing=build_editorial_timing_policy(
            config=source.config, target_seconds=30, memory_type="custom", transition="cut"
        ),
    )


def test_a_film_whose_month_titles_overrun_its_length_keeps_every_years_shot(tmp_path):
    years = _years(_titled(tmp_path))

    assert years.count(2018) == 1


def test_the_shots_the_timing_trim_cut_are_on_the_films_cut_record(tmp_path):
    source = _titled(tmp_path)

    plan = _plan(source)

    trimmed = json.loads(
        (source.artifact_dir / "derived-decisions" / "timing-trim.private.json").read_text()
    )["dropped"]
    assert trimmed
    cut = {c["asset_id"]: c["review_stage"] for c in plan["cut_carriers"]}
    assert {asset: cut.get(asset) for asset in trimmed} == dict.fromkeys(trimmed, "timing-trim")


def test_the_timing_trim_takes_a_years_only_shot_last():
    film = [
        {"asset_id": "g", "story_episode": "K1", "story_weight": "glimpse", "taken": "2018-04-07"},
        *(
            {"asset_id": f"m{n}", "story_episode": "K2", "story_weight": "minor", "taken": taken}
            for n, taken in enumerate(("2019-04-08", "2019-04-15", "2019-04-22"))
        ),
    ]

    kept, dropped = trim_to_timing_budget(
        film, lambda _shots: 10.5, 3.5, era_of=lambda taken: f"year-{taken[:4]}"
    )

    assert [c["asset_id"] for c in dropped] == ["m2"]
    assert [c["asset_id"] for c in kept] == ["g", "m0", "m1"]


def _works_years(tmp_path, *, second_stands: bool):
    """2018 holds two stories: first in funding order a works day with the partner whose frames
    mostly miss their subject, then a later visit. Ten starred 2019 days fill the other slots."""
    failing = Day(date(2018, 4, 7), "Garden works", moments=3, company="Robin (partner)")
    later = (
        Day(date(2018, 5, 19), "Garden works again", starred=True)
        if second_stands
        else Day(date(2018, 5, 19), "Garden works again", company="Robin (partner)")
    )
    busy = [
        Day(date(2019, 3, 2) + timedelta(days=7 * n), f"Works day {n + 1}", moments=3, starred=True)
        for n in range(10)
    ]
    source = _renovation(tmp_path, [failing, later, *busy])
    missing = ("d000",) if second_stands else ("d000", "d001")
    for asset_id, row in list(source.audience_annotations.items()):
        if asset_id.startswith(missing):
            heads = (*row.heads, ("clip_frames", "subject_often_missing"))
            source.audience_annotations[asset_id] = replace(row, heads=heads)
    return source


def test_a_year_whose_first_story_fails_the_standing_gate_is_voiced_by_its_next(tmp_path):
    years = _years(_works_years(tmp_path, second_stands=True))

    assert years.count(2018) == 1


def test_a_year_where_no_story_stands_stays_quiet_and_the_record_says_why(tmp_path):
    source = _works_years(tmp_path, second_stands=False)

    years = _years(source)

    selection = json.loads(
        (source.artifact_dir / "derived-decisions" / "story-selection.private.json").read_text()
    )
    assert 2018 not in years
    assert selection["quiet_partitions"] == [
        {
            "partition": "year-2018",
            "stories": ["S001", "S002"],
            "reason": "no picture of these stories stands on its own",
        }
    ]
