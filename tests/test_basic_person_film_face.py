"""On Basic, Immich's recognised face is people evidence even when the people head saw
nobody (#2359): a person film's every picture holds its subject by construction."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from immich_memories.analysis.reading.annotation_lines import AssetAnnotationLine
from tests.editorial_film_fixtures import Day, film_source


def _basic_plan(source) -> dict:
    from immich_memories.analysis.film.contract import StructurePlannerPorts
    from immich_memories.analysis.stories.rule_reader import NoModelJudge, RuleStructureReader
    from immich_memories.analysis.structure.planner import plan_structure

    return plan_structure(
        source,
        StructurePlannerPorts(
            judge=NoModelJudge(),
            # WHY: no preview hashes in a fixture library; the duplicate review has nothing to read.
            thumbnail_hash=lambda _asset: None,
            rules=RuleStructureReader(source),
        ),
    ).plan


def _dinners(tmp_path, people_head: str):
    """Dinners at the table: the frame head reads a table and a plate, and Immich recognised
    the film's subject on every picture. No caption: the Basic tier."""
    days = [
        Day(
            date(2024, 6, 1) + timedelta(days=3 * n),
            f"Dinner {n}",
            people=("Ada",),
            company="Ada (daughter; inner circle)",
        )
        for n in range(4)
    ]
    source = film_source(
        tmp_path,
        days,
        seconds=40,
        span=(date(2024, 6, 1), date(2024, 6, 30)),
        product="person_spotlight",
        pictures=2,
    )
    for asset_id, row in list(source.audience_annotations.items()):
        source.audience_annotations[asset_id] = AssetAnnotationLine(
            asset_id,
            row.text,
            description=None,
            heads=(
                ("nsfw_marqo", "no"),
                ("people", people_head),
                ("frame_kind", "lone_everyday_object"),
            ),
        )
    return source


@pytest.mark.feature("selection.basic-recognised-face")
def test_a_basic_person_film_keeps_pictures_whose_only_people_evidence_is_the_face(tmp_path):
    # The people head missed the small face at the table.
    plan = _basic_plan(_dinners(tmp_path, "none"))

    assert plan["carriers"]


@pytest.mark.feature("selection.basic-recognised-face")
def test_an_undetermined_people_head_does_not_hide_the_recognised_face(tmp_path):
    plan = _basic_plan(_dinners(tmp_path, "undetermined"))

    assert plan["carriers"]


def test_the_same_dinners_already_stood_when_the_head_saw_the_person(tmp_path):
    plan = _basic_plan(_dinners(tmp_path, "one"))

    assert plan["carriers"]
